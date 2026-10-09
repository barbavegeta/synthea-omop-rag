# ADR-0013: LLM answering, citations, spend cap, and the model choice (Phase 6)

**Status:** accepted. Model choice made by the project owner after the dev pilot: **option C**, Claude Opus 5.5 answers and Claude Sonnet 5.5 rewrites notes. Budget cap: $75.

## Design
**One call per question.** The model sees the question, the as-of date, and the top 5 retrieved chunks, labelled `C1`–`C5` with their dated headers. The system prompt states the rules a careful reader of clinical notes applies: use only the excerpts; cite every item; "denies" and "no evidence of" mean absent; "h/o … resolved" and "Previously" mean historical; the latest note wins; family history is about relatives; otherwise answer "not documented".

**Structured outputs** (`output_config.format`, JSON schema) guarantee the response parses: `status` (answered / not_documented), `yes_no`, `items[{value, date, cited_chunks}]`, `explanation`.
- The schema is built **per request**, so `cited_chunks` is an enum of the labels actually shown. The model *cannot* cite a chunk it never saw.
- Whether a cited chunk actually *supports* the claim is checked separately (grounding, Phase 7).

**Model parameters.**
- `output_config.effort` is set explicitly, because Opus 5.5 defaults to `medium` and Sonnet 5.5 to `high`.
- Thinking is left at the model default (adaptive, always on for Opus 5.5).
- `max_tokens` is 4,000.
- The server-side refusal fallback (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) is enabled. Its Python type was verified against the installed SDK, not assumed.

**Provider-agnostic.** A `Provider` protocol, selected by `llm.provider` or `LLM_PROVIDER`. Implemented: `anthropic` (Claude API) and `fake` (deterministic, free, for CI). `LLM_MODEL` and `LLM_BUDGET_USD` override config at run time.

**Hard spend cap.**
- Every API call is written to `llm.spend_ledger` (Postgres) at the price of the model that *served* it. Unknown models are charged at the most expensive known rate.
- Before sending, the client reserves the worst case (estimated input + `max_tokens` output, × 2 in case a refusal fallback bills a second model). If ledger spend + in-flight reservations + this reservation would exceed the cap, the call is **refused before anything is sent**.
- Thread-safe, so parallel calls can't jointly overshoot.
- Tests prove the refusal sends nothing and that the cap holds across runs, because spend is read back from the ledger.

**Response cache** (`llm.response_cache`): keyed by SHA-256 of provider + exact request. Reruns replay at $0 and are deterministic. Refusals and truncated outputs are not cached, so they can be retried.

**Grading is deterministic, with no LLM judge**: one rule per template (exact date; numeric within rounding *and* date; ingredient-set match; yes/no; ≥ 60% content-word overlap for stop reasons; abstention). Abstaining when an answer exists is wrong and flagged `over_abstained`.

## The pilot (dev, 44 questions stratified 4 per template)
| Model, effort | Correct | Billed input / output tokens per call | $ / call |
|---|---|---|---|
| Opus 5.5, low | 40/44 | 2,771 / 131 | 0.0137 |
| Opus 5.5, medium | 40/44 | 2,771 / 143 | 0.0139 |
| Sonnet 5.5, low | 40/44 | 2,771 / 125 | 0.0068 |
| Sonnet 5.5, medium | 40/44 | 2,771 / 130 | 0.0068 |

- **All 4 errors were retrieval misses**: the gold evidence was not among the 5 excerpts shown, the same 4 questions in every run. **With evidence present, all four configurations were 40/40.**
- In two latest-lab misses the model **abstained** rather than reporting an older value: the correct behaviour without the latest evidence.
- The two models are indistinguishable on this sample. It's a ceiling effect on clean template text, so a small difference can't be excluded.
- **Estimator calibration:** text-only token estimates undercounted billed input (about 1,820 vs 2,771; the gap is request overhead such as the structured-output format), and output was far below the assumed 600. Both constants were recalibrated. The cap was never at risk, because its reservation is dominated by `max_tokens`.

## Decision: option C
The pilot showed no measurable benefit from Opus on clean template notes, at 2× the price. Its extra capability is most likely to matter on **messy** text, so:
- **Opus 5.5 (effort low)** answers: the clean test set under all four retrieval configurations, plus the messy test set under the best configuration;
- **Sonnet 5.5** performs the note rewrite (a simpler text-transformation task).

Projected total about $66 of $75. Each step will be priced by dry run first; the cap makes overspending impossible, but a mis-estimated last step could stop early.

## Pilot spend
$1.82: four pilot runs plus one key-check call.
