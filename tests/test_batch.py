import json

import pytest

from rwe import db
from rwe.config import load_config
from rwe.llm.client import (
    BatchRunner,
    BudgetExceededError,
    LlmClient,
    LlmRequest,
    ProviderResponse,
)

CFG = load_config("default").llm


class FakeBatchProvider:
    """Billable, in-memory batch API: every request succeeds with fixed usage."""

    name = "batchtest"
    billable = True

    def __init__(self):
        self.batches: dict[str, list[tuple[str, LlmRequest]]] = {}
        self.ended = True

    def submit_batch(self, items):
        batch_id = f"b{len(self.batches) + 1}"
        self.batches[batch_id] = items
        return batch_id

    def batch_status(self, batch_id):
        return ("ended" if self.ended else "in_progress"), {
            "succeeded": len(self.batches[batch_id])
        }

    def batch_results(self, batch_id):
        for key, req in self.batches[batch_id]:
            yield (
                key,
                ProviderResponse(json.dumps({"ok": key[:6]}), "end_turn", req.model, 1000, 100),
                None,
            )

    def call(self, req):  # pragma: no cover - batches only
        raise AssertionError("direct call not expected")


def reqs(n):
    return [
        LlmRequest(
            model="claude-sonnet-5-5",
            system="s",
            user=f"u{i}",
            schema={},
            effort="low",
            max_tokens=1000,
            purpose="batchtest",
        )
        for i in range(n)
    ]


@pytest.fixture
def conn(db_conn):
    db.bootstrap(db_conn)
    db_conn.execute("truncate llm.spend_ledger, llm.response_cache, llm.batch, llm.batch_request")
    db_conn.commit()
    return db_conn


@pytest.mark.db
def test_batch_is_chunked_to_fit_the_cap_and_billed_at_half_price(conn):
    provider = FakeBatchProvider()
    one = BatchRunner(LlmClient(conn, CFG, provider)).worst_case(reqs(1)[0])
    client = LlmClient(conn, CFG.model_copy(update={"budget_usd": one * 3.5}), provider)
    runner = BatchRunner(client)

    batch_id, waiting = runner.submit(reqs(5), "t")
    assert len(provider.batches[batch_id]) == 3 and waiting == 2  # only 3 worst cases fit

    # a second submit before collecting sends nothing new: the 3 are in flight, no headroom
    with pytest.raises(BudgetExceededError):
        runner.submit(reqs(5), "t")

    status, _ = runner.collect(batch_id, log=lambda *_: None)
    assert status == "collected"
    per_call = (1000 * 2.0 + 100 * 10.0) / 1e6 * 0.5  # Sonnet prices, 50% batch discount
    spent = float(conn.execute("select sum(cost_usd) from llm.spend_ledger").fetchone()[0])
    assert spent == pytest.approx(3 * per_call)
    assert client.spent == pytest.approx(spent)  # reservation released, real cost booked

    batch2, waiting2 = runner.submit(reqs(5), "t")  # now the remaining 2 go
    assert len(provider.batches[batch2]) == 2 and waiting2 == 0


@pytest.mark.db
def test_unfinished_batch_stays_reserved_across_clients(conn):
    provider = FakeBatchProvider()
    provider.ended = False
    client = LlmClient(conn, CFG.model_copy(update={"budget_usd": 10.0}), provider)
    batch_id, _ = BatchRunner(client).submit(reqs(2), "t")
    assert BatchRunner(client).collect(batch_id)[0] == "in_progress"
    # a brand-new client (another process) still counts the reservation against the cap
    assert LlmClient(conn, CFG, provider).spent > 0


class TruncatingBatchProvider(FakeBatchProvider):
    """Every response stops at max_tokens, as a too-long rewrite does."""

    def batch_results(self, batch_id):
        for key, req in self.batches[batch_id]:
            yield key, ProviderResponse('{"partial', "max_tokens", req.model, 1000, 1000), None


@pytest.mark.db
def test_truncated_requests_are_not_resubmitted(conn):
    """Regression: a submit/collect loop re-paid for the same 21 truncated rewrites 15 times."""
    provider = TruncatingBatchProvider()
    runner = BatchRunner(LlmClient(conn, CFG.model_copy(update={"budget_usd": 10.0}), provider))
    batch_id, _ = runner.submit(reqs(2), "t")
    runner.collect(batch_id, log=lambda *_: None)
    assert runner.submit(reqs(2), "t") == (None, 0)  # nothing cached, but nothing resent
    again, _ = runner.submit(reqs(2), "t", retry_truncated=True)  # only when asked
    assert len(provider.batches[again]) == 2
