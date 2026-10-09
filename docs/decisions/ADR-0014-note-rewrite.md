# ADR-0014: LLM rewrite of notes into messier text, keeping exact ground truth (Phase 6b)

**Status:** accepted. Owner's decisions: the rewrite is done by Claude Sonnet 5.5 (option C, ADR-0013), on the 150 **test** patients' notes, with a 5-patient dev sample first. The spending order puts the essentials first (below).

## Why
On clean template notes the generator was never the bottleneck (pilot, ADR-0013): every answer error was a retrieval miss. Template text is far more regular than real notes, so any accuracy measured on it is an optimistic upper bound. A messier copy of the same notes measures how much realistic noise costs, while keeping the ground truth exact.

## How the ground truth survives
1. **Tag every fact** in the note with its index (`[[F12]]metformin[[/F12]]`), so fact ids are unchanged. Historical-condition prefixes ("h/o ", "history of ") are left *outside* the tag, so the model can rephrase how history is expressed.
2. **Rewrite** (Sonnet 5.5, effort low, structured output `{rewritten_note}`): terse, abbreviated, sections merged or reordered, varied wording for negation and history. Keep every tag and its inner text exactly, keep every date, keep each statement's meaning, add nothing.
3. **Validate deterministically** and reject the note (it keeps its template text) unless:
   - every tag appears exactly once with identical inner text, and no stray tag syntax remains;
   - every original date is still present;
   - the length ratio is within 0.4–1.6;
   - **meaning cues** are still there: a negation word in the clause of every negated fact, a past-time word in the clause of every historical fact, a relative in the clause of every family fact. Cues are whole-word matches *within the fact's own clause* (bounded by `.`, `;` or a newline). The first version matched substrings over a fixed window, and a unit test caught it accepting a rewrite whose only "history" cue was the "Hx" inside a neighbouring "FHx".
4. **Recompute spans** from the tag positions (`eval.note_fact_rewritten`), then strip the tags.

**Sanity check:** an identity rewrite (the fake provider echoing the tagged note) passes the validator for **188/188** dev-sample and **5,626/5,626** test notes, so the validator doesn't reject the template's own phrasing.

## Retrieval over the messy notes
Strategy `fixed_rw`: the chosen chunking (fixed 800/160), over each rewritten patient's notes. The rewritten text is used where valid, the template text otherwise, so every chart stays complete. Relevance labels use the recomputed spans. Template indexes are untouched (chunk sync is now scoped by strategy).

## Dev sample results (5 patients, 188 notes; real Sonnet 5.5 calls)
- **188/188 passed validation.** Median similarity to the template **0.47** (difflib ratio; 1.0 = identical), median length 0.80×. Example phrasing: "OP NOTE", "PMH:", "dx", "FHx:", "Prev on:", "last rx", "pt denies", "A/P:", "Amox/clav stopped … d/t …".
- Cost **$1.66**: $0.0088 per note direct, 646 output tokens on average, maximum 1,239. The batch price will be about $0.0044 per note.
- **Retrieval preview** (32 answerable dev questions; too few to conclude): messy notes lower R@1 across retrievers (hybrid_recency 0.84 → 0.78, BM25 0.66 → 0.56). R@5 holds for hybrid_recency (0.91) and BM25 (0.84); dense R@5 drops most (0.78 → 0.66).

## Limitations (stated in the write-up)
- **Fact strings stay verbatim.** The mess is in everything around them (wording, structure, abbreviations, how negation and history are phrased), not in the facts themselves. Real notes would also misspell and paraphrase the facts.
- The cue checks catch gross meaning drift, not every subtle change. A sample of rewrites is read by hand.
- Rejected notes fall back to the template, which makes the "messy" set slightly cleaner than it appears. The rejection rate is reported.

## Budget mechanics added in this step
- **Message Batches** (50% price) for the test rewrite and the test answers.
- A submitted batch's worst case stays **reserved in Postgres** until collected, so the cap holds across processes. Collection books the real cost (50%) and releases the reservation.
- **Chunked submission:** a batch takes as many requests as fit under the cap, and the rest wait for the next submit after a collection. Tested with an in-memory billable batch provider.
- `max_tokens` lowered from measurements: answers 4,000 → 1,500 (pilot max 207), rewrites 3,000 → 2,000 (sample max 1,239). Truncations are recorded as failures, never silently accepted.

## Spending order (owner's decision)
Spent so far **$3.48 of $75**. Remaining, in order, each priced by dry run first:
1. Opus 5.5 answers the clean test set with hybrid_recency and BM25: ≈ $16.50
2. Sonnet 5.5 rewrites the test notes (batch): ≈ $25
3. Opus 5.5 answers the messy test set with hybrid_recency: ≈ $8
4. If headroom remains: Opus 5.5 answers the clean test set with plain hybrid and dense: ≈ $16.50

Step 4 is part of the same pre-declared evaluation. Nothing about the system changes between installments.

## Test rewrite results (150 patients, 5,626 notes; Sonnet 5.5 via Message Batches)
- **5,565 valid (98.9%)**. 45 were rejected by the validator: 10 had changed or missing tags, 4 lost a date, and the rest lost a negation, history or family cue in a fact's clause. **16 were truncated** at `max_tokens` 2,000 (the longest notes). All 61 keep their template text in the messy corpus (the "slightly cleaner than it appears" limitation above).
- **Cost: $31.00.** That includes about **$3.90 of avoidable spend**: truncated responses are (correctly) never cached, and the submit/collect loop I ran resubmitted the same 16–21 truncated notes every round, 328 billed attempts in total. A truncation recurs, so the retries bought nothing. **Fix:** `BatchRunner.submit` now skips any request whose earlier attempt stopped at `max_tokens`, unless `retry_truncated=True` is passed explicitly. A regression test (`test_truncated_requests_are_not_resubmitted`) reproduces the incident.
- Messy index (`fixed_rw`): 8,566 chunks over the 150 test patients and the 5 dev-sample patients.
