from datetime import date

import pytest

from rwe.config import load_config
from rwe.rag import chunk, evaluate, retrieve
from rwe.rag.embed import FakeEmbedder

NOTE_TEXT = (
    "OUTPATIENT NOTE\nDate: 2023-04-12\nPatient: female, born 1960\n\n"
    "PAST MEDICAL HISTORY\n- HTN, diagnosed 2015-01-01\n- T2DM, diagnosed 2016-02-02\n\n"
    "MEDICATIONS\nCurrent: metformin (metformin 500 MG).\n\n"
    "REVIEW OF SYSTEMS\nDenies chest pain, fever.\n\n"
    "ASSESSMENT AND PLAN\nNo evidence of heart failure.\n"
)
NOTE = chunk.NoteRow(1, 7, date(2023, 4, 12), "Outpatient", NOTE_TEXT)


def test_section_chunks_cover_sections_with_dated_headers():
    chunks = chunk.section_chunks(NOTE, max_chars=1000)
    assert [c.section for c in chunks] == [
        "PAST MEDICAL HISTORY",
        "MEDICATIONS",
        "REVIEW OF SYSTEMS",
        "ASSESSMENT AND PLAN",
    ]
    meds = chunks[1]
    assert meds.content.startswith("Outpatient note, 2023-04-12, MEDICATIONS:\n")
    assert "metformin" in NOTE_TEXT[meds.char_start : meds.char_end]


def test_long_sections_split_on_line_boundaries_only():
    pieces = chunk._split_lines(NOTE_TEXT, 0, len(NOTE_TEXT), max_chars=60)
    for _start, end in pieces:
        assert end == len(NOTE_TEXT) or NOTE_TEXT[end - 1] == "\n"
    assert pieces[0][0] == 0 and pieces[-1][1] == len(NOTE_TEXT)
    assert all(pieces[i][1] == pieces[i + 1][0] for i in range(len(pieces) - 1))


def test_fixed_chunks_overlap_and_cover_the_note():
    chunks = chunk.fixed_chunks(NOTE, size=80, overlap=20)
    assert chunks[0].char_start == 0 and chunks[-1].char_end == len(NOTE_TEXT)
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end  # overlapping windows: no gaps
        assert NOTE_TEXT[a.char_end - 1] in " \n" or a.char_end == len(NOTE_TEXT)  # no cut words


def test_rrf_uses_ranks_and_breaks_ties_deterministically():
    fused = retrieve.rrf([["a", "b", "c"], ["c", "a", "d"]], k=60)
    assert fused[0] == "a"  # ranks 1 and 2 beat ranks 3 and 1
    assert retrieve.rrf([["x"], ["y"]], k=60) == ["x", "y"]  # tie -> by id


def test_recency_rerank_only_reorders_the_window_newest_first():
    dates = {
        "a": date(2020, 1, 1),
        "b": date(2024, 1, 1),
        "c": date(2024, 1, 1),
        "d": date(2025, 1, 1),
    }
    # window 3: b and c share a date and keep their order; d stays outside the window
    assert retrieve.recency_rerank(["a", "b", "c", "d"], dates, 3) == ["b", "c", "a", "d"]


def test_temporal_cue_detection_uses_whole_words():
    cfg = load_config("default").rag
    r = retrieve.Retriever.__new__(retrieve.Retriever)
    r.cfg = cfg
    assert r.is_temporal("What was this patient's most recent HbA1c?")
    assert r.is_temporal("Does this patient currently have asthma?")
    assert not r.is_temporal("When was this patient first diagnosed with asthma?")
    assert not r.is_temporal("Is there a concurrent condition?")  # 'current' inside a word


def test_tokenizer_keeps_negation_words():
    assert retrieve.tokenize("Denies chest pain. No evidence of HTN") == [
        "denies",
        "chest",
        "pain",
        "no",
        "evidence",
        "htn",
    ]


def test_fake_embedder_is_deterministic_and_normalised():
    cfg = load_config("ci").rag
    a, b = FakeEmbedder(cfg).query("metformin dose"), FakeEmbedder(cfg).query("metformin dose")
    assert (a == b).all() and abs(float((a**2).sum()) - 1.0) < 1e-5


def test_first_relevant_rank_and_summary():
    assert evaluate.first_relevant_rank(["a", "b", "c"], {"c"}) == 3
    assert evaluate.first_relevant_rank(["a"], {"z"}) is None
    import pandas as pd

    per_q = pd.DataFrame({"strategy": "s", "mode": "m", "rank": [1, 3, None, 2]})
    s = evaluate.summarise(per_q, [1, 3], ["strategy", "mode"]).iloc[0]
    assert s["recall@1"] == 0.25 and s["recall@3"] == 0.75
    assert s["MRR"] == round((1 + 1 / 3 + 0 + 1 / 2) / 4, 3)


def test_test_split_is_guarded():
    with pytest.raises(evaluate.TestSetGuardError):
        evaluate.load_questions(None, "test")
