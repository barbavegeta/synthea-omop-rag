from rwe.notes import rewrite
from rwe.notes.rewrite import FactSpan

TEXT = (
    "PAST MEDICAL HISTORY\n- T2DM, diagnosed 2015-05-01\n"
    "- h/o Acute bronchitis, resolved 2021-06-20\n"
    "FAMILY HISTORY\nMother: Hypertension.\n"
    "REVIEW OF SYSTEMS\nDenies chest pain.\n"
)


def span(sub: str) -> tuple[int, int]:
    s = TEXT.index(sub)
    return s, s + len(sub)


FACTS = [
    FactSpan(0, *span("T2DM"), "affirmed", "current", "patient"),
    FactSpan(1, *span("h/o Acute bronchitis"), "affirmed", "historical", "patient"),
    FactSpan(2, *span("Hypertension"), "affirmed", "current", "family"),
    FactSpan(3, *span("chest pain"), "negated", "current", "patient"),
]
TAGGED = rewrite.tag_note(TEXT, FACTS)


def test_tagging_leaves_history_prefix_outside_the_tag():
    assert "[[F0]]T2DM[[/F0]]" in TAGGED
    assert "h/o [[F1]]Acute bronchitis[[/F1]]" in TAGGED  # prefix free to be rephrased
    assert rewrite.TAG_RE.sub(lambda m: m.group(2), TAGGED) == TEXT


GOOD = (
    "PMH: [[F0]]T2DM[[/F0]] dx 2015-05-01; prev [[F1]]Acute bronchitis[[/F1]] "
    "(resolved 2021-06-20). FHx: mom - [[F2]]Hypertension[[/F2]]. ROS neg for "
    "[[F3]]chest pain[[/F3]]."
)


def test_valid_rewrite_recomputes_exact_spans():
    v = rewrite.validate(TEXT, TAGGED, GOOD, FACTS)
    assert v.ok, v.reason
    for f in FACTS:
        s, e = v.spans[f.index]
        assert v.text[s:e] in {"T2DM", "Acute bronchitis", "Hypertension", "chest pain"}
    assert "[[" not in v.text


def check(rewritten: str) -> str:
    return rewrite.validate(TEXT, TAGGED, rewritten, FACTS).reason


def test_validator_rejects_dropped_or_changed_facts():
    assert "missing [3]" in check(GOOD.replace("[[F3]]chest pain[[/F3]]", "chest pain"))
    assert "text changed" in check(GOOD.replace("[[F0]]T2DM[[/F0]]", "[[F0]]DM2[[/F0]]"))


def test_validator_rejects_lost_dates_and_meaning_drift():
    assert "dates lost" in check(GOOD.replace("(resolved 2021-06-20)", "(resolved)"))
    assert "negation cue lost" in check(GOOD.replace("ROS neg for", "ROS:"))
    assert "relative lost" in check(GOOD.replace("FHx: mom - ", "Also "))
    drift = GOOD.replace(
        "prev [[F1]]Acute bronchitis[[/F1]] (resolved 2021-06-20)",
        "[[F1]]Acute bronchitis[[/F1]] 2021-06-20",
    )
    assert "history cue lost" in check(drift)
