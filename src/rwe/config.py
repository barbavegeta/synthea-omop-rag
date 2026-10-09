"""Load config/pipeline.yaml, apply a named profile and validate it.

Validation is strict (unknown keys are errors) so a typo in the config fails loudly
instead of silently falling back to a default and changing a result.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "pipeline.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SyntheaConfig(_Strict):
    version: str
    jar_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generate: bool
    population: int = Field(gt=0)
    seed: int
    clinician_seed: int
    reference_date: date
    end_date: date
    years_of_history: int = Field(gt=0)
    state: str


class IngestConfig(_Strict):
    fhir_dir: Path

    def resolved_fhir_dir(self) -> Path:
        return self.fhir_dir if self.fhir_dir.is_absolute() else REPO_ROOT / self.fhir_dir


class VocabConfig(_Strict):
    source: Literal["athena", "stub"]  # stub: synthetic vocabulary for CI (ADR-0006)
    dir: Path

    def resolved_dir(self) -> Path:
        return self.dir if self.dir.is_absolute() else REPO_ROOT / self.dir


class AnalysisConfig(_Strict):
    output_dir: Path
    min_cell_count: int = Field(ge=0)  # counts 1..min_cell_count-1 reported as "<n"; 0 = off

    def resolved_output_dir(self) -> Path:
        return self.output_dir if self.output_dir.is_absolute() else REPO_ROOT / self.output_dir


class EvalConfig(_Strict):
    pool_min_age: int = Field(ge=0)
    pool_min_visits_in_window: int = Field(ge=1)
    pool_max_visits_total: int = Field(ge=1)
    dev_patients: int = Field(ge=1)
    test_patients: int = Field(ge=1)
    questions_per_patient: int = Field(ge=5)
    output_dir: Path

    def resolved_output_dir(self) -> Path:
        return self.output_dir if self.output_dir.is_absolute() else REPO_ROOT / self.output_dir


class NotesConfig(_Strict):
    window_start: date
    abbreviation_rate: float = Field(ge=0, le=1)
    no_evidence_rate: float = Field(ge=0, le=1)
    family_history_rate: float = Field(ge=0, le=1)
    stop_reason_rate: float = Field(ge=0, le=1)


class RagConfig(_Strict):
    embedder: Literal["bge", "fake"]
    model_name: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    query_instruction: str
    dim: int = Field(gt=0)
    chunkings: list[Literal["section", "fixed"]]
    chunking: Literal["section", "fixed"]  # the one used for answering and the final evaluation
    section_max_chars: int = Field(gt=100)
    fixed_chunk_chars: int = Field(gt=100)
    fixed_overlap_chars: int = Field(ge=0)
    rrf_k: int = Field(gt=0)
    candidate_depth: int = Field(gt=0)
    temporal_cues: list[str]
    recency_window: int = Field(gt=0)
    k_values: list[int]
    batch_size: int = Field(gt=0)


class LlmConfig(_Strict):
    provider: Literal["anthropic", "fake"]
    model: str
    effort: Literal["low", "medium", "high", "xhigh", "max"]
    rewrite_model: str
    max_tokens: int = Field(gt=0)
    budget_usd: float = Field(ge=0)
    top_k: int = Field(gt=0)
    retrieval_mode: Literal["bm25", "dense", "hybrid", "hybrid_recency"]
    fallbacks: Literal["default", "none"]
    prices: dict[str, tuple[float, float]]

    def with_env(self) -> LlmConfig:
        """Apply LLM_PROVIDER / LLM_MODEL / LLM_BUDGET_USD overrides from the environment."""
        updates = {}
        if v := os.environ.get("LLM_PROVIDER"):
            updates["provider"] = v
        if v := os.environ.get("LLM_MODEL"):
            updates["model"] = v
        if v := os.environ.get("LLM_BUDGET_USD"):
            updates["budget_usd"] = float(v)
        return LlmConfig(**{**self.model_dump(), **updates}) if updates else self

    def price(self, model: str) -> tuple[float, float]:
        """USD per million [input, output]; unknown models at the most expensive known rate."""
        return self.prices.get(model) or max(self.prices.values(), key=lambda p: p[1])


class PipelineConfig(_Strict):
    profile: str
    database: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    seed: int
    synthea: SyntheaConfig
    ingest: IngestConfig
    vocab: VocabConfig
    analysis: AnalysisConfig
    eval: EvalConfig
    notes: NotesConfig
    rag: RagConfig
    llm: LlmConfig

    def fingerprint(self) -> str:
        """Short, stable hash of the resolved config, recorded in every run manifest."""
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return base with override applied key by key, recursing into nested dicts."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(profile: str | None = None, path: Path = DEFAULT_CONFIG_PATH) -> PipelineConfig:
    raw = yaml.safe_load(path.read_text())
    profiles = raw.pop("profiles", {}) or {}
    profile = profile or os.environ.get("RWE_PROFILE") or "default"
    if profile != "default":
        if profile not in profiles:
            known = ", ".join(["default", *profiles])
            raise ValueError(f"Unknown profile {profile!r}; known profiles: {known}")
        raw = deep_merge(raw, profiles[profile])
    return PipelineConfig(profile=profile, **raw)
