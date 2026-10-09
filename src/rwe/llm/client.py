"""LLM calls with a hard budget cap, a response cache, and swappable providers (ADR-0013).

Budget: before every call, the worst case is reserved -- estimated input tokens plus
max_tokens of output, at the requested model's price, doubled in case a server-side
refusal fallback bills a second model. A call whose reservation would push total spend
(the Postgres ledger plus in-flight reservations) over the cap is refused BEFORE any
request is sent. After the call the actual cost, priced at the model that actually
served it, is written to the ledger.

Cache: responses are keyed by a SHA-256 of the provider plus the exact request. A rerun
replays them at $0, which also makes reruns deterministic (sampling is not).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from typing import Protocol

import psycopg
from psycopg.types.json import Jsonb

from rwe.config import LlmConfig

FALLBACK_FACTOR = 2.0  # worst case: the requested model declines and a fallback model reruns
CHARS_PER_TOKEN = 3.0  # conservative: English text averages nearer 4 characters per token
# Calibrated on the Phase 6 pilot: text-only estimates averaged ~1,820 tokens per answer
# request while billed input averaged 2,771; the difference is request overhead such as
# the structured-output format. Rounded up to stay conservative.
REQUEST_OVERHEAD_TOKENS = 1000


class BudgetExceededError(RuntimeError):
    """The call was not sent: its worst-case cost would exceed the hard cap."""


@dataclass(frozen=True)
class LlmRequest:
    model: str
    system: str
    user: str
    schema: dict
    effort: str
    max_tokens: int
    purpose: str  # e.g. "answer:<run_name>", recorded in the ledger

    def payload(self) -> dict:
        d = asdict(self)
        d.pop("purpose")  # the same request for a different purpose is the same request
        return d

    def cache_key(self, provider: str) -> str:
        canonical = json.dumps({"provider": provider, **self.payload()}, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def estimated_input_tokens(self) -> int:
        chars = len(self.system) + len(self.user) + len(json.dumps(self.schema))
        return int(chars / CHARS_PER_TOKEN) + REQUEST_OVERHEAD_TOKENS


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    stop_reason: str
    model_served: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    request_id: str | None = None


@dataclass(frozen=True)
class LlmResult:
    text: str
    parsed: dict | None
    stop_reason: str
    model_served: str
    cost_usd: float
    cached: bool
    cache_key: str


class Provider(Protocol):
    name: str
    billable: bool  # False only for the fake CI provider

    def call(self, req: LlmRequest) -> ProviderResponse: ...


def cost_usd(cfg: LlmConfig, r: ProviderResponse) -> float:
    """Actual cost, at the price of the model that served the request. Cache writes are
    billed at 1.25x and cache reads at 0.1x the input price."""
    price_in, price_out = cfg.price(r.model_served)
    input_equiv = r.input_tokens + 1.25 * r.cache_write_tokens + 0.1 * r.cache_read_tokens
    return (input_equiv * price_in + r.output_tokens * price_out) / 1e6


class LlmClient:
    def __init__(self, conn: psycopg.Connection, cfg: LlmConfig, provider: Provider) -> None:
        self.conn, self.cfg, self.provider = conn, cfg, provider
        self._lock = threading.Lock()  # guards the connection and the reservation arithmetic
        self._reserved = 0.0
        self._spent = self._ledger_total()

    def _ledger_total(self) -> float:
        """Spent so far, plus the reservations of batches submitted but not yet collected."""
        with self._lock:
            row = self.conn.execute(
                """select (select coalesce(sum(cost_usd), 0) from llm.spend_ledger)
                        + (select coalesce(sum(reserved_usd), 0) from llm.batch
                           where status = 'submitted')"""
            )
            return float(row.fetchone()[0])

    @property
    def spent(self) -> float:
        return self._spent

    def reservation(self, req: LlmRequest) -> float:
        if not self.provider.billable:
            return 0.0
        price_in, price_out = self.cfg.price(req.model)
        worst = (req.estimated_input_tokens() * price_in + req.max_tokens * price_out) / 1e6
        return worst * FALLBACK_FACTOR

    def cached(self, req: LlmRequest) -> dict | None:
        key = req.cache_key(self.provider.name)
        with self._lock:
            row = self.conn.execute(
                "select response from llm.response_cache where cache_key = %s", (key,)
            ).fetchone()
        return row[0] if row else None

    def complete(self, req: LlmRequest) -> LlmResult:
        key = req.cache_key(self.provider.name)
        if (hit := self.cached(req)) is not None:
            return LlmResult(
                hit["text"],
                _parse(hit["text"]),
                hit["stop_reason"],
                hit["model_served"],
                0.0,
                True,
                key,
            )

        hold = self.reservation(req)
        with self._lock:
            if self._spent + self._reserved + hold > self.cfg.budget_usd:
                raise BudgetExceededError(
                    f"Refused before sending: spent ${self._spent:.4f} + in flight "
                    f"${self._reserved:.4f} + this call's worst case ${hold:.4f} would exceed "
                    f"the ${self.cfg.budget_usd:.2f} cap."
                )
            self._reserved += hold
        try:
            r = self.provider.call(req)
        except Exception:
            with self._lock:
                self._reserved -= hold
            raise

        cost = cost_usd(self.cfg, r) if self.provider.billable else 0.0
        status = {"end_turn": "ok", "refusal": "refusal", "max_tokens": "max_tokens"}.get(
            r.stop_reason, r.stop_reason
        )
        parsed = _parse(r.text) if status == "ok" else None
        with self._lock:
            self._reserved -= hold
            self._spent += cost
            self.conn.execute(
                """insert into llm.spend_ledger (provider, model_requested, model_served, purpose,
                       cache_key, input_tokens, output_tokens, cost_usd, status, request_id)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    self.provider.name,
                    req.model,
                    r.model_served,
                    req.purpose,
                    key,
                    r.input_tokens + r.cache_write_tokens + r.cache_read_tokens,
                    r.output_tokens,
                    cost,
                    status,
                    r.request_id,
                ),
            )
            if parsed is not None:  # only clean answers are cached; failures can be retried
                self.conn.execute(
                    """insert into llm.response_cache (cache_key, request, response)
                       values (%s, %s, %s) on conflict (cache_key) do nothing""",
                    (
                        key,
                        Jsonb(req.payload()),
                        Jsonb(
                            {
                                "text": r.text,
                                "stop_reason": r.stop_reason,
                                "model_served": r.model_served,
                            }
                        ),
                    ),
                )
            self.conn.commit()
        return LlmResult(r.text, parsed, r.stop_reason, r.model_served, cost, False, key)


BATCH_DISCOUNT = 0.5  # Message Batches bill all tokens at 50%; server-side fallbacks don't apply


class BatchRunner:
    """Submit/collect Message Batches through the same ledger, cap and cache.

    Submit reserves the batch's worst case (at batch prices, no fallback factor) in
    llm.batch, so the cap counts it until collection, across processes. Collect writes
    each request's real cost to the ledger, caches clean responses, and releases the
    reservation. Providers without a batch API (the fake one) run requests inline.
    """

    def __init__(self, client: LlmClient) -> None:
        self.client = client

    def worst_case(self, req: LlmRequest) -> float:
        return self.client.reservation(req) / FALLBACK_FACTOR * BATCH_DISCOUNT

    def submit(
        self,
        reqs: list[LlmRequest],
        label: str,
        max_requests: int = 2000,
        retry_truncated: bool = False,
    ) -> tuple[str | None, int]:
        """Submit as many not-yet-answered requests as fit under the cap (and max_requests),
        as one batch. Returns (batch_id, requests still waiting). Waiting requests go in a
        later submit, once a collected batch has released its reservation: large jobs are
        chunked automatically instead of being refused outright."""
        c = self.client
        pending = {r.cache_key(c.provider.name): r for r in reqs if c.cached(r) is None}
        with c._lock:
            in_flight = {
                k
                for (k,) in c.conn.execute(
                    """select r.cache_key from llm.batch_request r join llm.batch b using (batch_id)
                   where b.status = 'submitted'"""
                ).fetchall()
            }
        # A truncation (stop_reason max_tokens) recurs on resubmission and is never cached,
        # so without this guard a submit/collect loop pays for it again every round.
        with c._lock:
            truncated = {
                k
                for (k,) in c.conn.execute(
                    "select distinct cache_key from llm.spend_ledger where status = 'max_tokens'"
                ).fetchall()
            }
        pending = {
            k: r
            for k, r in pending.items()
            if k not in in_flight and (retry_truncated or k not in truncated)
        }
        if not pending:
            return None, 0
        if not hasattr(c.provider, "submit_batch"):  # fake provider: run inline, no batch
            for r in pending.values():
                c.complete(r)
            return None, 0
        with c._lock:
            headroom = c.cfg.budget_usd - c._spent - c._reserved
        todo, hold = {}, 0.0
        for k, r in pending.items():
            cost = self.worst_case(r)
            if hold + cost > headroom or len(todo) >= max_requests:
                break
            todo[k], hold = r, hold + cost
        if not todo:
            raise BudgetExceededError(
                f"Batch refused before submitting: headroom ${headroom:.4f} under the "
                f"${c.cfg.budget_usd:.2f} cap cannot cover even one request's worst case."
            )
        with c._lock:
            batch_id = c.provider.submit_batch([(k, r) for k, r in todo.items()])
            c.conn.execute(
                """insert into llm.batch (batch_id, label, provider, n_requests, reserved_usd,
                       status) values (%s, %s, %s, %s, %s, 'submitted')""",
                (batch_id, label, c.provider.name, len(todo), hold),
            )
            with c.conn.cursor() as cur:
                cur.executemany(
                    """insert into llm.batch_request (batch_id, cache_key, model, purpose, request)
                       values (%s, %s, %s, %s, %s)""",
                    [
                        (batch_id, k, r.model, r.purpose, Jsonb(r.payload()))
                        for k, r in todo.items()
                    ],
                )
            c.conn.commit()
            c._spent += hold  # counts against the cap until collected
        return batch_id, len(pending) - len(todo)

    def collect(self, batch_id: str, log=print) -> tuple[str, dict]:
        """Returns (status, counts). Writes results only once the batch has ended."""
        c = self.client
        status, counts = c.provider.batch_status(batch_id)
        if status != "ended":
            return status, counts
        with c._lock:
            reqs = {
                k: (model, purpose, req)
                for k, model, purpose, req in c.conn.execute(
                    "select cache_key, model, purpose, request from llm.batch_request"
                    " where batch_id = %s",
                    (batch_id,),
                ).fetchall()
            }
            reserved = float(
                c.conn.execute(
                    "select reserved_usd from llm.batch where batch_id = %s", (batch_id,)
                ).fetchone()[0]
            )
        total = 0.0
        for key, r, error in c.provider.batch_results(batch_id):
            model, purpose, payload = reqs[key]
            if r is None:
                status_row, cost = f"batch_{error}", 0.0  # errored/expired requests are not billed
            else:
                cost = cost_usd(c.cfg, r) * BATCH_DISCOUNT
                status_row = {
                    "end_turn": "ok",
                    "refusal": "refusal",
                    "max_tokens": "max_tokens",
                }.get(r.stop_reason, r.stop_reason)
            total += cost
            with c._lock:
                c.conn.execute(
                    """insert into llm.spend_ledger (provider, model_requested, model_served,
                           purpose, cache_key, input_tokens, output_tokens, cost_usd, status,
                           request_id) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        c.provider.name,
                        model,
                        r.model_served if r else None,
                        purpose,
                        key,
                        (r.input_tokens + r.cache_write_tokens + r.cache_read_tokens) if r else 0,
                        r.output_tokens if r else 0,
                        cost,
                        status_row,
                        batch_id,
                    ),
                )
                if r is not None and status_row == "ok" and _parse(r.text) is not None:
                    c.conn.execute(
                        """insert into llm.response_cache (cache_key, request, response)
                           values (%s, %s, %s) on conflict (cache_key) do nothing""",
                        (
                            key,
                            Jsonb(payload),
                            Jsonb(
                                {
                                    "text": r.text,
                                    "stop_reason": r.stop_reason,
                                    "model_served": r.model_served,
                                }
                            ),
                        ),
                    )
        with c._lock:
            c.conn.execute(
                "update llm.batch set status = 'collected', collected_at = now() "
                "where batch_id = %s",
                (batch_id,),
            )
            c.conn.commit()
            c._spent += total - reserved  # replace the reservation with the real cost
        log(f"collected batch {batch_id}: actual ${total:.4f} (reserved ${reserved:.4f})")
        return "collected", counts


def _parse(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError, TypeError:
        return None
    return value if isinstance(value, dict) else None
