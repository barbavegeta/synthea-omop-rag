# ADR-0011: Synthetic notes, exact ground truth, and the frozen question set

**Status:** accepted (Phase 4). Scope choices made by the project owner: 75 dev / 150 test patients, notes for visits since 2016, only evaluation patients indexed.

## Why generate notes at all, and not use Synthea's?
Synthea already writes a note per encounter (DocumentReference, ADR-0005). Those notes carry no labels, though: nothing says which sentence is negated, historical or about a relative. Evaluating RAG on negation and temporality errors needs **ground truth at the level of each statement**, so the notes are generated here from the CDM, with every statement labelled as it is written.

## Design
**Source.** Notes are generated from **OMOP CDM tables, not FHIR**, so every fact traces to a CDM row and the Phase 7 SQL baseline queries exactly the data the notes were written from. Drugs are named by their RxNorm **ingredient** (via CONCEPT_ANCESTOR), so "metformin" means the same thing in notes, questions and gold answers.

**Patients.**
- Pool: alive, adult, at least 5 visits since 2016, at most 300 visits in total (758 eligible).
- A seeded sample of 225 patients, split **by patient** into 75 dev / 150 test, so no patient's notes inform both sets.
- One note per visit since 2016: 8,692 notes, median 870 characters.

**Exact ground truth.** Every statement is written through `NoteBuilder.fact()`, which records its character span **at write time**. `eval.note_fact` (173,820 facts) stores each fact with:
- type and label, plus concept id where there is one;
- value and date;
- **polarity** (affirmed / negated), **temporality** (current / historical, relative to the note date), **experiencer** (patient / family);
- **source** (`cdm` or `note_only`), and whether it was abbreviated.

Verified: **0 of 173,820 spans differ from the note text.**

**Planted phenomena** (all deterministic, seeded per patient, labelled):
| Phenomenon | How it appears |
|---|---|
| Negation | ROS "Denies chest pain, SOB, …" (symptoms); "No evidence of <condition>" for conditions the patient never has, checked across the **whole concept hierarchy** (a T2DM patient is never told "no evidence of diabetes") |
| Historical vs current | PMH lists active conditions with diagnosis dates, and conditions resolved in the last 3 years as "h/o … resolved <date>"; MEDICATIONS lists current and "Previously: … (last prescribed <date>)" |
| Family history | 1–3 relatives with chronic conditions, including ones the patient doesn't have |
| Abbreviations | HTN, T2DM, HLD, CKD, SOB, h/o, … at a 50% rate where a term has one |
| Note-only facts | family history, negated symptoms, and **drug stop reasons** |

**Stop reasons are clinically plausible per drug.** Class effects: lisinopril → dry cough, statins → muscle aches, metformin → GI intolerance. One-off prescriptions → "the course being completed". The first version assigned reasons at random; a manual read found "cough medicine stopped due to dry cough". That was corrected before freezing.

**Questions.** 8 per patient: 5 core templates where available, the rest chosen with a seed from the optional ones. Each question has:
- a gold answer;
- **gold supporting fact ids** (which define retrieval relevance in Phase 5 and citable evidence in Phase 7);
- a phenomenon label;
- `sql_answerable`.

| Template | Phenomenon | SQL? | Gold |
|---|---|---|---|
| latest_lab | lookup | yes | value, unit, date |
| dx_date | lookup | yes | first diagnosis date (conditions recorded once only) |
| current_medications | lookup | yes | set of ingredients active on the last note date (THEMIS rule, ADR-0007) |
| condition_current / condition_historical | temporality | yes | yes / no as of the last note |
| negation_trap | negation | yes | **no** (only ever written as "No evidence of …") |
| family_trap | family_history | yes | **no** (only a relative has it) |
| family_history | note_only | **no** | yes + which relative |
| stop_reason | note_only | **no** | the written reason |
| stop_reason_undocumented, lab_not_documented | abstention | partly | **not documented** |

**Freezing.** Questions are written to `eval/questions_{dev,test}.jsonl`, and the test file's SHA-256 to `eval/test_set.sha256`. Regenerating the test set with any difference **raises an error** unless `--refreeze` is passed explicitly. It was re-frozen once, before any retrieval code existed (the stop-reason fix), and the guard then proved a later refactor changed nothing (same hash).

## Known properties to respect when reporting
- **"No" outnumbers "yes"** on yes/no questions (495 vs 274), so results must be reported **per template**, never as a pooled yes/no accuracy.
- **57% of `current_medications` golds are empty**, a direct consequence of the 30-day prescription rule at the last visit.
- Notes are **template text**: far more regular than real clinical notes. Any retrieval or answer accuracy here is an **optimistic upper bound**. The optional LLM paraphrase pass (Phase 6) exists to measure how much messiness costs.
- Symptom negation checks the patient's active conditions by keyword, which is a heuristic.
- Only conditions whose names match the abbreviation list can be abbreviated, so about 6% of current-condition mentions are abbreviated versus about 51% of historical ones (which also use "h/o").
