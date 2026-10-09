# ADR-0015: Final evaluation design (Phase 7)

**Status:** accepted. Owner's decision on the gold bug: fix the generator and re-freeze the test set (details below).

## What is scored, and how often
The test split (150 patients, 1,200 questions) is scored **once**, after all dev tuning stopped. `load_questions(split="test")` raises unless the caller passes `final=True`. Only `rwe final` and `rwe report` pass it. Runs are pre-declared in ADR-0014's spending order. Nothing about the system (prompt, k, retrieval settings, chunking, model) changes between them.

## Metrics
| What | Definition | Unit of uncertainty |
|---|---|---|
| **Retrieval** recall@k, MRR | A chunk is relevant if it contains a gold fact span. Abstention questions (no gold facts) are excluded. | per question |
| **Answer accuracy** | Deterministic per-template grader (ADR-0013), no LLM judge: yes/no must match (family history also needs the right relative); a lab needs a number within max(0.011, 0.5%) of gold **and** the gold date; dates exact; medication sets need every gold ingredient and no extras; stop reasons need ≥60% of the gold reason's content words | per question |
| **Grounding** | For each claimed item, at least one cited excerpt must support **every stated component**: its date (if any) is stated, all its numbers are stated, and ≥60% of its content words are. This checks *attribution* (the excerpt says it), not truth; accuracy covers truth. | per claim |
| **Abstention** | Precision and recall of "not documented", with the two error kinds named: over-abstention and answering the unanswerable | per question |
| **SQL baseline** | Hand-written SQL over the CDM for each structured template. Note-only templates (family history, stop reasons) are N/A. | per question |

**CIs:** 95% percentile bootstrap that resamples **patients** (2,000 reps, fixed seed). The same patient's questions share notes and errors, so resampling questions would make the intervals too narrow. Comparisons whose intervals overlap heavily are reported as "not distinguishable", not as wins.

## How the grounding rule was settled (on dev pilot answers, before test)
1. *Literal value in a cited chunk.* Too strict: "Course completed" vs the note's "the course being completed" failed.
2. *Value or date or ≥60% of words.* Too permissive: a claim with the **wrong number** passed because its words matched.
3. **All stated components must be supported** (chosen). Pilot grounding came out at 0.86–0.92. The remaining flags I read were genuine, e.g. a claim adding a diagnosis date that isn't in the cited excerpt.

An automatic rule is only as good as its agreement with a human. `rwe grounding-sample` draws 50 random claims from the main test run into a CSV without the automatic label (kept in a separate file so the labeller isn't anchored). The owner labels them, and the agreement (and Cohen's κ) is reported next to the grounding numbers.

## Failure taxonomy (every wrong answer; first match wins)
`no_valid_response` → `answered_unanswerable` → `retrieval_miss` → `over_abstention` → `negation_error` → `family_attribution` → `temporal_error` → `other`.

`retrieval_miss` comes **before** `over_abstention`. When the evidence was never shown, "not documented" is the right response to what the model saw, so the failure belongs to retrieval. Retrieval misses are then split into **abstained (safe)** and **answered wrongly (unsafe)**: in a clinical setting, the second kind is the one that matters. Examples per class are generated into `docs/failure_analysis.md`.

## Gold bug found during Phase 7 setup, and the re-freeze
While wiring the SQL baseline I compared it with gold on dev and test. On test, `latest_lab` gold for one question (p154) disagreed with SQL. The cause: when a patient had two results for the same lab **on the same day**, the question generator took the *first*, but the notes show the *last*, so the gold value (149.18) didn't appear in any note. Options were to (a) leave the bug and report it, (b) drop the question, or (c) fix the generator and re-freeze. The owner chose **(c)**. The fix takes the last value of the latest day. Regenerating changed **exactly one line** of `questions_test.jsonl` (p154-latest_lab: 149.18 → 164.32); dev and all notes were unchanged byte for byte. The new hash `6e78649b92ca…` is committed. No model output on test existed when this happened, so it doesn't bias any result. It is still a change to a frozen file, and it is disclosed here.

## Known definitional disagreement (kept, counted)
Dev person 461, `condition_current`: periodontal disease was diagnosed **and** resolved on the as-of date. Gold follows the note ("New diagnosis", so current); SQL says resolved. Neither is wrong; the question is ambiguous on that day. Gold is kept. Every test question where SQL and gold disagree is written to `eval/results/test/sql_vs_gold_disagreements.csv` and explained in the write-up, so the SQL "ceiling" isn't overstated.

On test there is exactly one: **p51 `family_trap`**, "Does this patient have seizure disorder?". Gold says no: the patient's notes mention it only for a relative. SQL says yes, because it counts **descendants** in the SNOMED hierarchy, and the patient had *eclampsia in pregnancy* (2023), which SNOMED places under seizure disorder. This is a genuine hierarchy-versus-wording ambiguity, not a bug in either. Gold is kept and the case is disclosed.

## Why the SQL baseline is a ceiling, not a competitor
Notes are generated from the CDM, and the gold comes from the same data with the same definitions. On structured questions SQL is right by construction, apart from the ambiguity above. The interesting results are therefore:
1. how close RAG gets to SQL on structured questions, and where it falls short (retrieval, not reasoning, per the pilot);
2. note-only questions, where SQL can't answer at all;
3. the difference between clean and messy notes, in either direction.

## Interpretation notes recorded with the results
- **Answer accuracy follows retrieval.** Across the four clean runs, accuracy ranks exactly as recall@5 does (dense 0.719 → 0.827, hybrid 0.775 → 0.867, BM25 0.845 → 0.908, hybrid_recency 0.894 → 0.925). Most errors are retrieval misses, and given the evidence the model rarely errs.
- **Clean vs messy is confounded by note length.** Messy hybrid_recency scored higher (0.942 vs 0.925, overlapping CIs). The rewritten notes are about 20% shorter, so the same 800-character chunking gives 14% fewer chunks per patient (55 vs 65), each carrying 13% more gold facts (14.5 vs 12.9). Five chunks therefore cover more evidence, and the gain concentrates in `latest_lab` (0.61 → 0.78). Messiness itself cost recall@1 for every retriever and cost `stop_reason` 1.00 → 0.80: all 12 misses were safe abstentions, because the terse rewrites share few words with "why was X stopped?". The result is reported as "no loss in aggregate, for a reason unrelated to messiness", not as "messy notes help". A fair test would fix the number of facts per chunk, or compare at equal token budgets.
- **Safety, not accuracy, separates the best two configurations.** When retrieval missed, BM25 answered wrongly 84 times and abstained 6 times; hybrid_recency answered wrongly 31 times and abstained 40 times.

## Grounding calibration: what was actually done
The design calls for the owner to hand-label the 50-claim sample. At the owner's request, Claude (Opus 5.5, the same model family as the answerer) labelled it first, without seeing the automatic labels, into a separate attributed file (`grounding_sample_claude_labels.csv`). The human file stays blank for a later pass, and the report lists each labeller separately.

Result: agreement 0.94, κ 0.77. All 3 disagreements were the rule rejecting supported claims: an abbreviation ("HTN"), dates split across two cited excerpts, and commentary wording. So the rule is conservative. All 6 unsupported claims added a diagnosis or resolution date absent from the cited excerpts, and the rule caught them all.

Caveat: an LLM reader shares failure modes with the LLM being judged. This is evidence about the rule's behaviour, not a substitute for human calibration.
