import json

import pytest

from rwe import db
from rwe.answer import grade, prompt
from rwe.config import load_config
from rwe.llm.client import BudgetExceededError, LlmClient, LlmRequest, ProviderResponse, cost_usd

CFG = load_config("default").llm


class CountingProvider:
    """Billable test double: returns a fixed answer and counts calls."""

    name = "test"
    billable = True

    def __init__(self, text='{"status": "answered"}', stop="end_turn"):
        self.calls, self.text, self.stop = 0, text, stop

    def call(self, req):
        self.calls += 1
        return ProviderResponse(self.text, self.stop, req.model, 1000, 200)


def request(**kw) -> LlmRequest:
    base = dict(
        model="claude-sonnet-5-5",
        system="s",
        user="u",
        schema={},
        effort="low",
        max_tokens=1000,
        purpose="test",
    )
    return LlmRequest(**{**base, **kw})


def test_cost_uses_the_served_models_price_and_unknown_models_are_priced_high():
    r = ProviderResponse("", "end_turn", "claude-sonnet-5-5", 1_000_000, 100_000)
    assert cost_usd(CFG, r) == pytest.approx(2.0 + 1.0)
    unknown = ProviderResponse("", "end_turn", "some-new-model", 1_000_000, 0)
    assert cost_usd(CFG, unknown) == pytest.approx(10.0)  # most expensive input rate


def test_cache_key_ignores_purpose_but_not_content():
    assert request(purpose="a").cache_key("p") == request(purpose="b").cache_key("p")
    assert request(user="x").cache_key("p") != request(user="y").cache_key("p")
    assert request().cache_key("p1") != request().cache_key("p2")


@pytest.fixture
def ledger(db_conn):
    db.bootstrap(db_conn)
    db_conn.execute("truncate llm.spend_ledger, llm.response_cache, llm.batch, llm.batch_request")
    db_conn.commit()
    return db_conn


@pytest.mark.db
def test_budget_refuses_before_sending(ledger):
    provider = CountingProvider()
    client = LlmClient(ledger, CFG.model_copy(update={"budget_usd": 0.0001}), provider)
    with pytest.raises(BudgetExceededError):
        client.complete(request())
    assert provider.calls == 0  # nothing was sent
    assert ledger.execute("select count(*) from llm.spend_ledger").fetchone()[0] == 0


@pytest.mark.db
def test_ledger_records_cost_and_cache_replays_free(ledger):
    provider = CountingProvider()
    client = LlmClient(ledger, CFG.model_copy(update={"budget_usd": 5.0}), provider)
    first = client.complete(request())
    second = client.complete(request(purpose="another run"))
    assert provider.calls == 1 and second.cached and second.cost_usd == 0.0
    assert first.cost_usd == pytest.approx((1000 * 2.0 + 200 * 10.0) / 1e6)
    total = ledger.execute("select sum(cost_usd) from llm.spend_ledger").fetchone()[0]
    assert float(total) == pytest.approx(first.cost_usd)
    # a fresh client reads spend from the ledger, so the cap holds across runs
    assert LlmClient(ledger, CFG, provider).spent == pytest.approx(first.cost_usd)


@pytest.mark.db
def test_refusals_are_charged_but_never_cached(ledger):
    provider = CountingProvider(text="", stop="refusal")
    client = LlmClient(ledger, CFG.model_copy(update={"budget_usd": 5.0}), provider)
    result = client.complete(request())
    assert result.parsed is None and result.stop_reason == "refusal"
    client.complete(request())
    assert provider.calls == 2  # retried, not replayed from cache
    assert ledger.execute("select count(*) from llm.response_cache").fetchone()[0] == 0


def test_schema_only_allows_shown_chunk_labels():
    s = prompt.schema(3)
    enum = s["properties"]["items"]["items"]["properties"]["cited_chunks"]["items"]["enum"]
    assert enum == ["C1", "C2", "C3"]
    assert "[C2] second" in prompt.user_message("q?", "2025-01-01", ["first", "second"])


def answer(status="answered", yes_no="not_applicable", items=(), explanation=""):
    return {"status": status, "yes_no": yes_no, "items": list(items), "explanation": explanation}


def item(value, date=""):
    return {"value": value, "date": date, "cited_chunks": ["C1"]}


@pytest.mark.parametrize(
    "gold, template, ans, expected",
    [
        ({"type": "not_documented"}, "lab_not_documented", answer(status="not_documented"), True),
        ({"type": "not_documented"}, "lab_not_documented", answer(items=[item("7")]), False),
        ({"type": "yes_no", "value": False}, "negation_trap", answer(yes_no="no"), True),
        (
            {"type": "yes_no", "value": False},
            "negation_trap",
            answer(status="not_documented"),
            False,
        ),
        (
            {"type": "yes_no", "value": True, "relative": "father"},
            "family_history",
            answer(yes_no="yes", items=[item("Father: hyperlipidemia")]),
            True,
        ),
        (
            {"type": "yes_no", "value": True, "relative": "father"},
            "family_history",
            answer(yes_no="yes", items=[item("Mother")]),
            False,
        ),
        (
            {"type": "lab", "value": 27.97, "unit": "kg/m2", "date": "2025-12-10"},
            "latest_lab",
            answer(items=[item("27.97 kg/m2", "2025-12-10")]),
            True,
        ),
        (
            {"type": "lab", "value": 27.97, "unit": "kg/m2", "date": "2025-12-10"},
            "latest_lab",
            answer(items=[item("27.97 kg/m2", "2024-01-01")]),
            False,
        ),
        (
            {"type": "date", "date": "2009-09-09"},
            "dx_date",
            answer(items=[item("T2DM", "2009-09-09")]),
            True,
        ),
        (
            {"type": "set", "items": ["metformin"]},
            "current_medications",
            answer(items=[item("Metformin hydrochloride")]),
            True,
        ),
        (
            {"type": "set", "items": ["metformin"]},
            "current_medications",
            answer(items=[item("metformin"), item("lisinopril")]),
            False,
        ),
        ({"type": "set", "items": []}, "current_medications", answer(), True),
        (
            {"type": "text", "value": "persistent dry cough"},
            "stop_reason",
            answer(items=[item("stopped because of a persistent dry cough")]),
            True,
        ),
    ],
)
def test_grader(gold, template, ans, expected):
    correct, _ = grade.grade({"answer": gold, "template": template}, json.loads(json.dumps(ans)))
    assert correct is expected


def test_over_abstention_is_flagged():
    ok, detail = grade.grade(
        {"answer": {"type": "date", "date": "2020-01-01"}, "template": "dx_date"},
        answer(status="not_documented"),
    )
    assert not ok and detail["over_abstained"]


@pytest.mark.db
def test_empty_retrieval_fails_loudly_instead_of_sending_no_context(db_conn):
    """Regression (ADR-0012 correction): an empty result once produced an invalid request."""
    from rwe.answer import run

    class NothingRetriever:
        def search(self, mode, person_id, query, k):
            return []

    db.bootstrap(db_conn)
    cfg = load_config("default")
    q = {"question_id": "p1-x", "person_id": 1, "question": "q?", "as_of": "2025-01-01"}
    with pytest.raises(RuntimeError, match="retrieved nothing for p1-x"):
        run.build_requests(db_conn, NothingRetriever(), cfg, [q], "m", "low", "dense", "t")
