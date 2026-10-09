# ADR-0004: Reproducibility (config file, seeds, run manifest)

**Status:** accepted (revised in Phase 1 after testing on real output)

## Decision
- **One config file** (`config/pipeline.yaml`) holds every parameter that can change a result. It is validated strictly (unknown keys are errors), so a typo cannot silently fall back to a default.
- **Profiles** (`ci`) override defaults key by key, so the 20-patient CI run differs from the full run *only* in what it names.
- **Synthea is pinned on four axes**, each found necessary by testing, not assumed:
  - `-s` / `-cs`: patient and clinician seeds.
  - `-r` **and** `-e`: the reference date (base for population ages) **and** the end date (when the simulation stops). The first version of this ADR assumed `-r` was enough. Inspecting real output found encounters dated 2026 with `-r 20251231`, because `-e` defaults to the real *today*.
  - `-Duser.timezone=UTC`: the JVM renders timestamps in the machine's local zone. On the development machine (Europe/London) the output mixed `+00:00` and `+01:00` offsets, so another machine would write different strings, and near midnight, different dates.
  - The jar itself: release 4.0.0, verified by SHA-256 before every run.
- **Verified, not assumed:** generating the CI population twice gives byte-identical bundles (same digest over all files).
- **Run manifest** per run: git SHA and dirty flag, Python and package versions, platform, resolved config and its fingerprint, seeds, Synthea version and jar hash, and an **input digest**, a SHA-256 over every bundle's name and uncompressed content. The gzipped CI fixture and the raw Synthea output give the same digest, which proves the fixture is unmodified.

## Known limits
- LLM outputs are not bit-reproducible even at temperature 0. Phase 6 caches every response keyed by (provider, model, parameters, prompt), so reruns replay identical outputs at zero cost.
- Bit-identical floating-point results across CPUs and BLAS builds are not guaranteed for embeddings. Retrieval rankings may differ in rare near-ties.
