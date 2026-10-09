"""Deterministic answer grading against the SQL-derived gold answers (ADR-0013).

No LLM judge: every rule below is exact or near-exact, so a grade can be explained and
re-derived. Each result carries a detail dict used by the Phase 7 failure analysis.
  not_documented gold  correct iff the model abstained
  yes/no               the yes_no field matches; family history also needs the relative
  lab                  a numeric value within rounding of gold AND the gold date
  date                 an item dated (or valued) exactly the gold date
  set (medications)    every gold ingredient matched and no extra ingredient; empty gold
                       requires an answered, empty list
  text (stop reason)   >= 60% of the gold reason's content words appear in the answer
A model that abstains when an answer exists is wrong, and flagged `over_abstained`.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
WORD = re.compile(r"[a-z]+")
STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "to",
        "of",
        "due",
        "by",
        "and",
        "or",
        "for",
        "was",
        "were",
        "on",
        "in",
        "with",
        "patient",
    ]
)


def _texts(ans: dict) -> list[str]:
    return [i["value"] for i in ans.get("items", [])] + [ans.get("explanation", "")]


def _content_words(text: str) -> set[str]:
    return {w for w in WORD.findall(text.lower()) if w not in STOP and len(w) > 2}


def grade(question: dict, ans: dict | None) -> tuple[bool, dict]:
    gold, template = question["answer"], question["template"]
    if ans is None:
        return False, {"error": "no parsable answer"}
    abstained = ans.get("status") == "not_documented"
    if gold["type"] == "not_documented":
        return abstained, {"abstained": abstained}
    if abstained:
        return False, {"over_abstained": True}
    items = ans.get("items", [])

    if gold["type"] == "yes_no":
        ok = ans.get("yes_no") == ("yes" if gold["value"] else "no")
        detail = {"yes_no": ans.get("yes_no")}
        if ok and "relative" in gold:
            ok = any(gold["relative"] in t.lower() for t in _texts(ans))
            detail["relative_ok"] = ok
        return ok, detail

    if gold["type"] == "lab":
        target, day = float(gold["value"]), gold["date"]
        tol = max(0.011, 0.005 * abs(target))
        value_ok = date_ok = False
        for item in items:
            nums = [float(n) for n in NUMBER.findall(item["value"])]
            v = any(abs(n - target) <= tol for n in nums)
            d = item["date"] == day or day in item["value"]
            value_ok |= v
            date_ok |= d
            if v and d:
                return True, {"value_ok": True, "date_ok": True}
        return False, {"value_ok": value_ok, "date_ok": date_ok}

    if gold["type"] == "date":
        ok = any(item["date"] == gold["date"] or gold["date"] in item["value"] for item in items)
        return ok, {"predicted_dates": [i["date"] for i in items]}

    if gold["type"] == "set":
        want = [g.lower() for g in gold["items"]]
        got = [i["value"].lower() for i in items if i["value"].strip()]
        matched = {g for g in want if any(g in p or p in g for p in got)}
        extra = [p for p in got if not any(g in p or p in g for g in want)]
        ok = len(matched) == len(want) and not extra
        return ok, {"missing": sorted(set(want) - matched), "extra": extra, "empty_gold": not want}

    if gold["type"] == "text":
        want = _content_words(gold["value"])
        have = set().union(*(_content_words(t) for t in _texts(ans)))
        overlap = len(want & have) / len(want) if want else 0.0
        return overlap >= 0.6, {"overlap": round(overlap, 2)}

    raise ValueError(f"unknown gold type {gold['type']!r} for template {template}")
