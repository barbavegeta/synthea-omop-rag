"""The answering prompt and its structured-output schema (ADR-0013).

The schema is built per request so that `cited_chunks` can only contain the labels of the
excerpts actually shown (C1..Ck): the model cannot cite a chunk it never saw. Structured
outputs guarantee the response parses; whether the citations SUPPORT the claims is checked
separately (grounding, Phase 7).
"""

from __future__ import annotations

SYSTEM = """You answer questions about one patient using ONLY the excerpts from that \
patient's clinical notes given in the message. The notes are synthetic.

Rules:
1. Use only the excerpts. If they do not contain the answer, set status to "not_documented". \
Do not guess.
2. Every item must cite the label(s) of the excerpt(s) that directly state it, e.g. "C2".
3. Negation: "denies X", "no evidence of X" and "negative for X" mean the patient does NOT \
have X.
4. Time: answer as of the date given. A condition written as "h/o ..." or "history of ... \
resolved <date>", or a medication listed under "Previously", is historical, not current. When \
excerpts disagree, the most recent note wins; "most recent" means the latest dated value.
5. Family history describes relatives, not the patient.
6. Notes use abbreviations (e.g. HTN = hypertension, T2DM = type 2 diabetes mellitus).
7. Write dates as YYYY-MM-DD and medications as ingredient names. For yes/no questions set \
yes_no to "yes" or "no"; otherwise set it to "not_applicable". If a list is empty (for \
example, no current medications), answer with status "answered" and no items."""


def labels(k: int) -> list[str]:
    return [f"C{i}" for i in range(1, k + 1)]


def schema(k: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["answered", "not_documented"]},
            "yes_no": {"type": "string", "enum": ["yes", "no", "not_applicable"]},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "date": {"type": "string"},
                        "cited_chunks": {
                            "type": "array",
                            "items": {"type": "string", "enum": labels(k)},
                        },
                    },
                    "required": ["value", "date", "cited_chunks"],
                    "additionalProperties": False,
                },
            },
            "explanation": {"type": "string"},
        },
        "required": ["status", "yes_no", "items", "explanation"],
        "additionalProperties": False,
    }


def user_message(question: str, as_of: str, chunks: list[str]) -> str:
    excerpts = "\n\n".join(
        f"[{label}] {text}" for label, text in zip(labels(len(chunks)), chunks, strict=True)
    )
    return (
        f"Question (answer as of {as_of}): {question}\n\n"
        f"Excerpts from this patient's notes:\n\n{excerpts or '(no excerpts retrieved)'}"
    )
