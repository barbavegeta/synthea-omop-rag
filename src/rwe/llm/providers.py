"""LLM providers. Select with config llm.provider or the LLM_PROVIDER environment variable.

Adding a provider means implementing `call(LlmRequest) -> ProviderResponse`; nothing else in
the pipeline changes. Implemented: anthropic (Claude API) and fake (CI: no network, $0).
"""

from __future__ import annotations

import json

from rwe.config import LlmConfig
from rwe.llm.client import LlmRequest, ProviderResponse

# Models that take output_config.effort and the server-side "default" fallback.
EFFORT_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"
    billable = True

    def __init__(self, cfg: LlmConfig) -> None:
        import anthropic  # credentials: ANTHROPIC_API_KEY (from .env) or an `ant auth` profile

        self.client = anthropic.Anthropic(max_retries=4)
        self.fallbacks = cfg.fallbacks

    @staticmethod
    def params(req: LlmRequest) -> dict:
        """Messages API parameters: shared by single calls and batch requests."""
        output_config: dict = {"format": {"type": "json_schema", "schema": req.schema}}
        if req.model in EFFORT_MODELS:
            output_config["effort"] = req.effort  # explicit: defaults differ by model
        return {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": [{"role": "user", "content": req.user}],
            "output_config": output_config,
        }

    def call(self, req: LlmRequest) -> ProviderResponse:
        kwargs = self.params(req)
        if self.fallbacks == "default" and req.model in EFFORT_MODELS:
            response = self.client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs
            )
        else:
            response = self.client.messages.create(**kwargs)
        return self._response(response)

    # -- Message Batches (no server-side fallback: the Batches API rejects it) ---------------
    def submit_batch(self, items: list[tuple[str, LlmRequest]]) -> str:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        batch = self.client.messages.batches.create(
            requests=[
                Request(custom_id=key, params=MessageCreateParamsNonStreaming(**self.params(req)))
                for key, req in items
            ]
        )
        return batch.id

    def batch_status(self, batch_id: str) -> tuple[str, dict]:
        b = self.client.messages.batches.retrieve(batch_id)
        c = b.request_counts
        return b.processing_status, {
            "processing": c.processing,
            "succeeded": c.succeeded,
            "errored": c.errored,
            "canceled": c.canceled,
            "expired": c.expired,
        }

    def batch_results(self, batch_id: str):
        """Yields (custom_id, ProviderResponse | None, error_type | None); any order."""
        for res in self.client.messages.batches.results(batch_id):
            if res.result.type == "succeeded":
                yield res.custom_id, self._response(res.result.message), None
            else:
                yield res.custom_id, None, res.result.type

    @staticmethod
    def _response(response) -> ProviderResponse:
        text = next((b.text for b in response.content if b.type == "text"), "")
        u = response.usage
        return ProviderResponse(
            text=text,
            stop_reason=response.stop_reason or "unknown",
            model_served=response.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(response, "_request_id", None),
        )


class FakeProvider:
    """Deterministic and free: always answers 'not documented'. Exercises every code path in
    CI; its answers are never reported as results."""

    name = "fake"
    billable = False

    def call(self, req: LlmRequest) -> ProviderResponse:
        if "rewritten_note" in json.dumps(req.schema):  # rewrite requests: echo the input
            answer = {"rewritten_note": req.user.split("\n\n", 1)[-1]}
        else:
            answer = {
                "status": "not_documented",
                "yes_no": "not_applicable",
                "items": [],
                "explanation": "fake provider",
            }
        return ProviderResponse(
            json.dumps(answer), "end_turn", "fake", req.estimated_input_tokens(), 40
        )


def make_provider(cfg: LlmConfig):
    return AnthropicProvider(cfg) if cfg.provider == "anthropic" else FakeProvider()
