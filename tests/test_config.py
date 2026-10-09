from datetime import date

import pytest
from pydantic import ValidationError

from rwe.config import deep_merge, load_config


def test_default_profile_loads():
    cfg = load_config("default")
    assert cfg.profile == "default"
    assert cfg.synthea.population == 1000
    assert cfg.synthea.reference_date == date(2025, 12, 31)


def test_ci_profile_overrides_only_what_it_names():
    default, ci = load_config("default"), load_config("ci")
    assert ci.synthea.population == 20
    assert ci.synthea.seed == default.synthea.seed
    assert ci.synthea.reference_date == default.synthea.reference_date


def test_profile_from_environment(monkeypatch):
    monkeypatch.setenv("RWE_PROFILE", "ci")
    assert load_config().profile == "ci"


def test_unknown_profile_is_an_error():
    with pytest.raises(ValueError, match="Unknown profile"):
        load_config("nope")


def test_unknown_key_is_an_error(tmp_path):
    bad = tmp_path / "pipeline.yaml"
    bad.write_text(
        "seed: 1\ndatabase: x\n"
        f"synthea: {{version: 4.0.0, jar_sha256: {'0' * 64}, generate: true, population: 5,\n"
        "          seed: 1, clinician_seed: 1, reference_date: 2025-01-01, end_date: 2025-01-01,\n"
        "          years_of_history: 10, state: Massachusetts, populaton: 7}\n"
        "ingest: {fhir_dir: x}\n"
        "vocab: {source: athena, dir: x}\n"
        "analysis: {output_dir: x, min_cell_count: 5}\n"
        "eval: {pool_min_age: 18, pool_min_visits_in_window: 1, pool_max_visits_total: 9,\n"
        "       dev_patients: 1, test_patients: 1, questions_per_patient: 8, output_dir: x}\n"
        "notes: {window_start: 2016-01-01, abbreviation_rate: 0.5, no_evidence_rate: 0.3,\n"
        "        family_history_rate: 0.25, stop_reason_rate: 0.6}\n"
        f"rag: {{embedder: fake, model_name: m, model_revision: {'a' * 40}, query_instruction: q,\n"
        "      dim: 8, chunkings: [section], chunking: section, section_max_chars: 500,\n"
        "      fixed_chunk_chars: 500,\n"
        "      fixed_overlap_chars: 0, rrf_k: 60, candidate_depth: 10, k_values: [1],\n"
        "      temporal_cues: [latest], recency_window: 5,\n"
        "      batch_size: 4}\n"
        "llm: {provider: fake, model: m, effort: low, rewrite_model: m, max_tokens: 10,\n"
        "      budget_usd: 0, top_k: 1,\n"
        "      retrieval_mode: bm25, fallbacks: none, prices: {m: [1, 2]}}\n"
    )
    with pytest.raises(ValidationError):
        load_config("default", path=bad)


def test_fingerprint_is_stable_and_sensitive():
    assert load_config("default").fingerprint() == load_config("default").fingerprint()
    assert load_config("default").fingerprint() != load_config("ci").fingerprint()


def test_deep_merge_recurses_without_mutating_input():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    merged = deep_merge(base, {"a": {"y": 20}})
    assert merged == {"a": {"x": 1, "y": 20}, "b": 3}
    assert base["a"]["y"] == 2
