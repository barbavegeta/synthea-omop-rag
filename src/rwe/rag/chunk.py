"""Two chunking strategies, compared on dev (ADR-0012).

Each chunk keeps [char_start, char_end) into the original note, so "does this chunk
contain gold fact X" is an exact span test, never fuzzy matching. The text that is
embedded and searched gets a short header with the note type and DATE: many questions
are temporal ("current", "most recent"), and a chunk cut out of its note would otherwise
lose when it was written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

SECTION_RE = re.compile(
    r"^(?:PAST MEDICAL HISTORY|FAMILY HISTORY|MEDICATIONS|REVIEW OF SYSTEMS"
    r"|OBJECTIVE|ASSESSMENT AND PLAN)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class NoteRow:
    note_id: int
    person_id: int
    note_date: date
    kind: str
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    strategy: str
    note_id: int
    person_id: int
    note_date: date
    section: str
    char_start: int
    char_end: int
    content: str  # header + note text slice: what gets embedded and keyword-indexed

    @property
    def content_sha(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()


def _header(note: NoteRow, section: str | None) -> str:
    where = f", {section}" if section else ""
    return f"{note.kind} note, {note.note_date.isoformat()}{where}:\n"


def _split_lines(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split [start, end) into pieces of at most max_chars, cutting only after newlines.
    A single line longer than max_chars stays whole rather than being cut mid-fact."""
    pieces, piece_start, cursor = [], start, start
    while cursor < end:
        nl = text.find("\n", cursor, end)
        line_end = end if nl == -1 else nl + 1
        if line_end - piece_start > max_chars and cursor > piece_start:
            pieces.append((piece_start, cursor))
            piece_start = cursor
        cursor = line_end
    if piece_start < end:
        pieces.append((piece_start, end))
    return pieces


def section_chunks(note: NoteRow, max_chars: int) -> list[Chunk]:
    starts = [m.start() for m in SECTION_RE.finditer(note.text)]
    bounds = list(zip(starts, [*starts[1:], len(note.text)], strict=True))
    chunks = []
    for s, e in bounds:
        section = note.text[s : note.text.find("\n", s)]
        for a, b in _split_lines(note.text, s, e, max_chars):
            body = note.text[a:b].strip("\n")
            if not body:
                continue
            i = len(chunks)
            chunks.append(
                Chunk(
                    f"section:{note.note_id}:{i}",
                    "section",
                    note.note_id,
                    note.person_id,
                    note.note_date,
                    section,
                    a,
                    b,
                    _header(note, section) + body,
                )
            )
    return chunks


def fixed_chunks(note: NoteRow, size: int, overlap: int, strategy: str = "fixed") -> list[Chunk]:
    """Sliding windows of `size` characters with `overlap`, ends snapped back to whitespace
    so words are not cut. The section label is the section the window starts in."""
    text, chunks, start = note.text, [], 0
    starts = [(m.start(), m.group(0)) for m in SECTION_RE.finditer(text)]
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            ws = max(text.rfind(" ", start, end), text.rfind("\n", start, end))
            if ws > start + size // 2:
                end = ws + 1
        section = next((name for pos, name in reversed(starts) if pos <= start), "HEADER")
        i = len(chunks)
        chunks.append(
            Chunk(
                f"{strategy}:{note.note_id}:{i}",
                strategy,
                note.note_id,
                note.person_id,
                note.note_date,
                section,
                start,
                end,
                _header(note, None) + text[start:end],
            )
        )
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks
