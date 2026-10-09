"""LLM rewrite of template notes into messier clinician-style text, keeping ground truth (ADR-0014).

Facts are wrapped in tags ([[F12]]metformin[[/F12]]; the tag number is the fact's index in
the note, so fact ids are unchanged). The model may rewrite everything AROUND the tags --
wording, order, abbreviations, how negation and history are expressed -- but must keep
every tag and its inner text exactly, keep every date, and keep each statement's meaning.

A deterministic validator then rejects any rewrite that:
  - drops, duplicates, renumbers or alters a tagged fact, or leaves stray tag syntax;
  - loses a date that was in the original;
  - leaves a negated fact without a negation cue nearby, a historical fact without a
    past-time cue nearby, or a family fact without a relative nearby (meaning drift);
  - changes length implausibly.
Rejected notes keep their template text. Spans are recomputed from the tag positions.
The cue checks are heuristics: they catch gross drift, not every subtle change, which is
why a sample of rewrites is also read by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TAG_RE = re.compile(r"\[\[F(\d+)\]\](.*?)\[\[/F\1\]\]")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
HISTORY_PREFIXES = ("h/o ", "history of ")

# Cues are matched as WHOLE words/phrases (so "hx" does not match inside "FHx", "no" not
# inside "known"), and only within the fact's own clause (see _clause).
NEGATION_CUES = (
    "no",
    "not",
    "denies",
    "denied",
    "deny",
    "negative",
    "neg",
    "without",
    "absent",
    "ruled out",
    "r/o",
    "never",
    "none",
    "nil",
    "free of",
    "w/o",
    "-ve",
)
HISTORY_CUES = (
    "h/o",
    "history",
    "hx",
    "previous",
    "previously",
    "prev",
    "prior",
    "past",
    "former",
    "formerly",
    "resolved",
    "discontinued",
    "stopped",
    "no longer",
    "last",
    "was",
    "had",
    "ago",
    "remote",
    "d/c",
    "dc'd",
    "ceased",
    "off",
    "completed",
    "s/p",
    "until",
)
RELATIVE_WORDS = (
    "mother",
    "father",
    "sister",
    "brother",
    "mom",
    "dad",
    "mum",
    "sibling",
    "siblings",
    "maternal",
    "paternal",
    "parent",
    "parents",
    "fhx",
    "fh",
    "family",
)
CLAUSE_END = re.compile(r"\.(?=\s|$)|[;\n]")  # a full stop ends a clause; "7.1" does not


def _cue_pattern(cues: tuple[str, ...]) -> re.Pattern:
    alternatives = "|".join(re.escape(c) for c in sorted(cues, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])")


NEGATION_RE = _cue_pattern(NEGATION_CUES)
HISTORY_RE = _cue_pattern(HISTORY_CUES)
RELATIVE_RE = _cue_pattern(RELATIVE_WORDS)

SYSTEM = """You rewrite synthetic clinical notes so they read like real notes written \
quickly by a busy clinician: terse fragments, common abbreviations, sections merged, \
reordered or renamed, varied phrasing (e.g. "pt denies", "neg for", "prev on", "stopped", \
"FHx:"). The notes are synthetic; no real patient is involved.

Hard rules:
1. Every tagged span like [[F7]]text[[/F7]] must appear exactly once in your output, with \
the same number and exactly the same text inside. Never add, remove, merge or renumber tags.
2. Keep every date (YYYY-MM-DD) exactly as written.
3. Keep the meaning of every statement: what is negated stays negated, what is past stays \
past (resolved, previous, stopped), and what is about a relative stays about that relative.
4. Do not add any clinical fact, value, date or medication that is not in the original."""


def output_schema() -> dict:
    return {
        "type": "object",
        "properties": {"rewritten_note": {"type": "string"}},
        "required": ["rewritten_note"],
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class FactSpan:
    index: int  # position of the fact in its note = tag number = suffix of the fact id
    start: int
    end: int
    polarity: str
    temporality: str
    experiencer: str


def tag_note(text: str, facts: list[FactSpan]) -> str:
    """Insert tags around fact spans. Historical-condition prefixes ('h/o ', 'history of ')
    are left OUTSIDE the tag so the model can rephrase how history is expressed."""
    out, cursor = [], 0
    for f in sorted(facts, key=lambda f: f.start):
        if f.start < cursor:
            raise ValueError(f"overlapping facts at {f.start}")
        start = f.start
        for prefix in HISTORY_PREFIXES:
            if text[start : f.end].startswith(prefix):
                start += len(prefix)
        out += [text[cursor:start], f"[[F{f.index}]]", text[start : f.end], f"[[/F{f.index}]]"]
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


def _clause(text: str, start: int, end: int, before: int, after: int) -> str:
    """The text around a fact, cut at clause boundaries (. ; newline) and at most
    `before`/`after` characters, so a cue in a NEIGHBOURING statement does not count."""
    left = max(0, start - before)
    boundaries = [m.end() for m in CLAUSE_END.finditer(text, left, start)]
    left = boundaries[-1] if boundaries else left
    right_end = min(len(text), end + after)
    m = CLAUSE_END.search(text, end, right_end)
    return text[left : m.start() if m else right_end].lower()


def _near(text: str, start: int, end: int, cues: re.Pattern, before: int, after: int) -> bool:
    return cues.search(_clause(text, start, end, before, after)) is not None


@dataclass(frozen=True)
class Validation:
    ok: bool
    reason: str
    text: str | None = None  # rewritten note with tags stripped
    spans: dict[int, tuple[int, int]] | None = None  # fact index -> new span


def validate(original_text: str, tagged: str, rewritten: str, facts: list[FactSpan]) -> Validation:
    want = {int(m.group(1)): m.group(2) for m in TAG_RE.finditer(tagged)}
    found = [(int(m.group(1)), m.group(2), m.start(), m.end()) for m in TAG_RE.finditer(rewritten)]
    ids = [i for i, *_ in found]
    if sorted(ids) != sorted(want):
        missing, extra = set(want) - set(ids), [i for i in ids if i not in want]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        return Validation(False, f"tags differ: missing {sorted(missing)} extra {extra} dup {dup}")
    for i, inner, *_ in found:
        if inner != want[i]:
            return Validation(False, f"tag F{i} text changed")

    # strip tags, tracking where each fact's inner text lands in the clean text
    clean, spans, cursor = [], {}, 0
    for i, inner, s, e in found:
        clean.append(rewritten[cursor:s])
        offset = sum(len(p) for p in clean)
        spans[i] = (offset, offset + len(inner))
        clean.append(inner)
        cursor = e
    clean.append(rewritten[cursor:])
    text = "".join(clean)
    if "[[" in text or "]]" in text:
        return Validation(False, "stray tag syntax")

    missing_dates = set(DATE_RE.findall(original_text)) - set(DATE_RE.findall(text))
    if missing_dates:
        return Validation(False, f"dates lost: {sorted(missing_dates)}")
    if not 0.4 <= len(text) / max(len(original_text), 1) <= 1.6:
        return Validation(False, f"length ratio {len(text) / max(len(original_text), 1):.2f}")

    for f in facts:
        s, e = spans[f.index]
        if f.polarity == "negated" and not _near(text, s, e, NEGATION_RE, 60, 0):
            return Validation(False, f"F{f.index}: negation cue lost")
        if f.temporality == "historical" and not _near(text, s, e, HISTORY_RE, 80, 60):
            return Validation(False, f"F{f.index}: history cue lost")
        if f.experiencer == "family" and not _near(text, s, e, RELATIVE_RE, 40, 0):
            return Validation(False, f"F{f.index}: relative lost")
    return Validation(True, "ok", text, spans)
