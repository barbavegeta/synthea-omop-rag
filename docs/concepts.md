# Concepts glossary

Short definitions of the ideas this project uses, each tied to where it appears in the code. Added to phase by phase.

## FHIR (source format)
- **FHIR R4**: HL7's standard for exchanging health data as JSON/XML **resources** (Patient, Encounter, Condition, Observation, MedicationRequest, ...).
- **Bundle**: a container of resources. Synthea writes one per patient, as a *transaction bundle*, where entries reference each other as `urn:uuid:<id>`.
- **CodeableConcept**: a coded value with one or more `coding`s (`system` URL + `code` + `display`). The system URL tells you the terminology, e.g. `http://loinc.org`.
- **US Core**: the US profile of FHIR. Race and ethnicity are *extensions* on Patient.

## OMOP CDM (target model)
- **CDM**: the OHDSI Common Data Model, a fixed relational schema (person, visit_occurrence, condition_occurrence, drug_exposure, measurement, ...). The same analysis code then runs on any CDM database.
- **Concept**: a row in `vocab.concept`, one clinical idea in one vocabulary, with an integer `concept_id`.
- **Standard vs source concept**: many vocabularies say the same thing. One concept per idea is designated **standard** (`standard_concept = 'S'`), and analyses use standard concepts. The original code's concept is kept as `*_source_concept_id`.
- **'Maps to'**: the relationship in `concept_relationship` from a source concept to its standard concept(s). A standard concept maps to itself. → `int_concept_map.sql`
- **Domain**: the kind of thing a standard concept is (Condition, Drug, Measurement, Observation, Procedure, ...). **It decides the CDM table**, not the source format. → `int_events_mapped.sql`
- **concept_id = 0**: "No matching concept". It's used when a code can't be mapped; the record is kept and its unmapped status stays visible.
- **Type concept**: provenance of a record, e.g. 32817 *EHR*, 32838 *EHR prescription*.
- **CONCEPT_ANCESTOR**: the hierarchy closure (every ancestor–descendant pair). "All descendants of type 2 diabetes" is one join. Used in Phase 3.
- **Observation period**: when a person's data is expected to be captured; the denominator for rates and the window for lookback. → ADR-0008
- **THEMIS**: OHDSI's ratified ETL conventions, e.g. drug end dates. → ADR-0007
- **Athena**: OHDSI's vocabulary download service.

## Observational research on the CDM (Phase 3)
- **Concept set**: a list of concepts, each optionally "with descendants", that together define a clinical idea (e.g. all T2DM codes). Defined as a seed and expanded through CONCEPT_ANCESTOR, as ATLAS does. → `seeds/concept_sets.csv`
- **Cohort**: a set of persons who satisfy criteria for a period of time. OHDSI stores it as `cohort(cohort_definition_id, subject_id, cohort_start_date, cohort_end_date)`. → `models/analysis/cohort.sql`
- **Index date**: the date each person enters the cohort (here, the first T2DM record). All covariate and outcome windows are defined relative to it.
- **Look-back (washout)**: observed time before index. It's needed to tell a *new* (incident) diagnosis from an old one first recorded late, and to measure baseline covariates. "Observed" matters: here it requires an actual visit, because a long observation period alone can hide years with no data.
- **Incident vs prevalent cohort**: incident = newly diagnosed people (clean index date); prevalent = everyone with the condition (index often arbitrary). Mixing them biases anything measured from index.
- **Attrition table**: how many people remain after each inclusion criterion. It lets a reader see exactly what the cohort excludes.
- **Characterisation (Table 1)**: baseline description of a cohort: demographics, comorbidities, prior drugs, baseline measurements.
- **Drug era**: continuous exposure built from individual drug records, merging gaps of 30 days or fewer (the OHDSI DRUG_ERA rule).
- **New-user design**: index = first-ever use of a drug, to avoid *prevalent-user bias* (people already on a drug are survivors of its early effects). Considered here, but not chosen because the cohort was too small.
- **Sensitivity analysis**: the same analysis repeated under a different reasonable assumption (here: with and without implausible HbA1c values), to show whether conclusions depend on it.
- **Small-cell suppression**: hiding counts below a threshold (often 5) before release, so individuals can't be re-identified. *Complementary* suppression also hides cells that would let a suppressed one be recalculated.
- **Pre-specification**: fixing the analysis before seeing the outcome data. Choices made after looking (like this project's 5-year horizon) must be reported as post hoc.

## Evaluation data (Phase 4)
- **Ground truth by construction**: the notes are generated from known data, so the right answer to every question is known exactly rather than labelled by hand afterwards.
- **Character span**: the exact (start, end) position of a statement in a note. Recorded when the text is written, so "which chunk contains this fact" is a lookup, not a guess.
- **Polarity / temporality / experiencer**: the three properties clinical NLP most often gets wrong. Is it *negated*? Is it *past or current*? Is it about the *patient or a relative*?
- **Dev / test split by patient**: dev is for tuning, test is touched once, for the final report. Splitting by question would leak one patient's notes into both.
- **Freezing**: fixing the test set (here by hash) before building the system, so it can't be tuned on.
- **Abstention**: answering "not documented" when the information isn't there, instead of guessing.

## Retrieval (Phase 5)
- **RAG**: retrieval-augmented generation. Find the relevant passages first, then have an LLM answer *from those passages*, citing them.
- **Chunk**: the unit that is retrieved, a section or a fixed-size window of a note. Too big dilutes the match; too small splits facts.
- **Embedding**: a vector representing a text's meaning. Similar texts have nearby vectors. **Cosine similarity** compares their direction.
- **pgvector / HNSW**: a Postgres extension for vector columns, and an approximate nearest-neighbour index (a layered graph) that avoids comparing the query with every vector. Approximate means it can miss neighbours; `ef_search` trades speed against recall.
- **BM25**: classic keyword ranking. A term counts more when it is frequent in the chunk (with saturation) and rare across the corpus (**IDF**, inverse document frequency), normalised for chunk length.
- **Dense vs sparse retrieval**: embeddings (meaning, robust to paraphrase) vs keywords (exact terms, codes and dates).
- **Reciprocal Rank Fusion**: combine rankings by summing 1/(k + rank). Ranks only, so no score calibration is needed.
- **recall@k / MRR**: share of questions with relevant evidence in the top k / mean of 1 / (rank of the first relevant result).
- **Recency-aware re-ranking**: similarity has no notion of time, so for "most recent" / "currently" questions, re-sort the strong matches newest-first.

## LLM answering (Phase 6)
- **Structured outputs**: the API constrains the response to a JSON schema, so it always parses. It guarantees *form*, not *truth*.
- **Citation / grounding**: each claim names the excerpts it came from. *Grounded* means a cited excerpt actually states the claim (checked in Phase 7).
- **Abstention**: answering "not documented" instead of guessing. *Over-abstention* is declining when the answer was available.
- **Effort / adaptive thinking**: how much the model reasons before answering. More effort means more output tokens, so more cost and latency.
- **Spend ledger / reservation**: record every call's real cost; before a call, hold its worst-case cost against the cap so the cap can't be crossed.
- **Response cache**: identical request, identical answer at $0; also what makes reruns reproducible.
- **Ceiling effect**: when every option scores near-perfectly, the test can't tell them apart. "No difference found" is not "no difference".

## dbt (transformation tool)
- **Model**: a `SELECT` saved as a `.sql` file. dbt builds it as a table or view. `ref('x')` links models and gives dbt the dependency graph (lineage).
- **Source**: a table dbt reads but does not build (`raw.fhir_resource`, `vocab.*`).
- **Seed**: a small CSV in the repo, loaded as a table, for reviewed mapping tables and reference data.
- **Data test**: a query that returns failing rows. Generic tests (`unique`, `not_null`, `relationships`) are configured in YAML; singular tests are `.sql` files in `tests/`.
- **Unit test**: fixed input rows → expected output rows for one model, run without real data. It proves the *logic*. → `models/_unit_tests.yml`
- **Severity**: `error` stops the build; `warn` reports and continues.
- **`dbt build`**: seeds, models and tests in dependency order. A model's tests run before anything downstream uses it.
