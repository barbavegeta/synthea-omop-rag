# ADR-0012: Chunking, embeddings and retrieval (Phase 5)

**Status:** accepted. Choices made by the project owner: compare both chunkings on dev; bge-small-en-v1.5; downloads approved.

## Decisions
**Patient-scoped retrieval.** Every search is restricted to one patient's chunks (a `person_id` filter), as chart search works. A question about a patient must never be answered from someone else's notes. Consequence, stated in the write-up: each query searches about 240 chunks, not the whole corpus, which makes retrieval easier than open-corpus search.

**Two chunking strategies, chosen on dev:**
- *section*: one chunk per note section (PMH, family history, medications, ROS, objective, assessment and plan); sections over 1,000 characters are split on line boundaries only.
- *fixed*: windows of 800 characters with 160 overlap, ends snapped back to whitespace.

Every chunk keeps `[char_start, char_end)` in its note, so **relevance is exact**: a chunk is relevant to a question if it contains a gold fact's whole span. The embedded and searched text starts with a header with note type and **date** (`Outpatient note, 2023-04-12, MEDICATIONS:`), because many questions are temporal and a chunk cut out of its note loses when it was written.

**Embeddings.**
- BAAI/bge-small-en-v1.5 (384-d, MIT), pinned to Hugging Face commit `5c38ec7c…`, run locally on CPU, with no paid API.
- L2-normalised, so cosine distance in pgvector ranks the same as inner product.
- The bge v1.5 query instruction prefix is applied to queries only, as the model card specifies.
- PyTorch comes from the CPU-only index; the default wheel would pull about 2.5 GB of CUDA libraries.
- The embedding stack is an optional extra; CI uses a deterministic hashing embedder and reports nothing from it.

**Indexing is resumable.** Chunks are keyed by id plus content hash, and embeddings are committed in batches of 1,024. Only new, changed, or differently-embedded chunks are processed. Measured throughput on this laptop (i5-1135G7, CPU only):
- about 17 chunks per second on the 800-character fixed chunks;
- 22–45 per second on the mostly short section chunks;
- 55,611 chunks in total in about an hour.

This mattered in practice. The first run was killed by the host's memory guard part-way through, and the rerun continued from the last committed batch. Once the pinned model is cached, the embedder runs with `HF_HUB_OFFLINE=1`.

**BM25** uses `bm25s`: real BM25, which Postgres `ts_rank` is not.
- Per-patient index, so IDF reflects that patient's chart.
- A small stopword list that deliberately **keeps** "no", "not" and "denies".
- No stemming.
- Chunks sharing no term with the query score 0 and are left unranked, rather than returned in arbitrary order.

**Dense** retrieval uses pgvector cosine distance (`<=>`). **Verified with EXPLAIN ANALYZE:** the patient-scoped query uses the B-tree `(strategy, person_id)` index and sorts that patient's rows **exactly** (about 1 ms). The HNSW index is *not* used, so dense retrieval here is exact k-NN, not approximate. HNSW is built and works for a global query. There, pgvector's default `hnsw.ef_search = 40` capped a `LIMIT 50` query at 40 rows. It doesn't affect these results, but it's worth knowing: `ef_search` must be at least k.

**Hybrid** uses Reciprocal Rank Fusion, `score = Σ 1/(60 + rank)`, over the top 50 of each retriever. It uses ranks only, so BM25 scores and cosine similarities never need calibrating against each other. Ties are broken by chunk id for determinism.

**Metrics:**
- **recall@k**: the share of questions with at least one relevant chunk in the top k, for k = 1, 3, 5, 10. Evidence is often redundant (a diagnosis date repeats in every later note), and one copy is sufficient.
- **MRR**: mean reciprocal rank of the first relevant chunk, within the top 50.
- Abstention questions have no evidence and are excluded here; abstention is scored on answers in Phase 7.
- **Dev only.** `load_questions(split="test")` raises unless called by the final Phase 7 evaluation.

**Fourth configuration: hybrid_recency** (added by the project owner after the dev results below showed every retriever failing on time-sensitive questions). The rule was fixed *before* it was evaluated:
- It applies only when the question contains a temporal cue (whole words: "most recent", "latest", "currently", "current", "as of").
- It re-sorts the hybrid top N newest-first by note date (equal dates keep hybrid order) and leaves the rest of the list unchanged.
- Non-temporal questions get plain hybrid.
- N was chosen on dev from the pre-declared grid {5, 10, 20}.

## Dev results (512 answerable dev questions; abstention questions excluded)
| Chunking | Retriever | R@1 | R@3 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|---|
| fixed | bm25 | 0.695 | 0.801 | 0.848 | 0.902 | 0.764 |
| fixed | dense | 0.574 | 0.664 | 0.701 | 0.785 | 0.640 |
| fixed | hybrid | 0.637 | 0.748 | 0.795 | 0.844 | 0.708 |
| fixed | hybrid_recency (N=20) | 0.799 | 0.881 | 0.896 | 0.902 | 0.843 |
| section | bm25 | 0.646 | 0.781 | 0.816 | 0.869 | 0.727 |
| section | dense | 0.604 | 0.680 | 0.695 | 0.754 | 0.654 |
| section | hybrid | 0.646 | 0.758 | 0.779 | 0.855 | 0.716 |
| section | hybrid_recency (N=20) | 0.816 | 0.887 | 0.898 | 0.912 | 0.854 |

Per-template and per-question results: `eval/results/dev/`. The recency window sweep is in `recency_window_sweep.csv`.

**What the dev results say**
- **BM25 beats dense by about 15 points of R@5.** Template notes reward exact terms and dates. For example, the as-of date in a current-medications question matches the chunk's date header word for word (BM25 R@5 = 1.00 there; dense 0.59).
- **Plain hybrid sits *between* the two, not above both.** RRF gives the weaker dense list equal weight and drags BM25 down. Fusion is not automatically better.
- **Time-sensitive questions fail for every similarity retriever.** Plain-hybrid R@5 is 0.43 for latest lab, 0.46 for current condition, and 0.34 for historical condition. Their evidence must come from the *latest* note, and similarity has no notion of time.
- **hybrid_recency fixes most of that.** Current condition goes 0.46 → 0.78, historical 0.34 → 0.81, and overall R@5 0.795 → 0.896. It does *not* fix latest_lab (0.56): the newest lab chunk is often not even in the hybrid top 20.
- **Recency window:** R@5 was 0.795 / 0.840 / 0.896 for N = 5 / 10 / 20. **20 is the edge of the pre-declared grid**, so the optimum may lie beyond it. The grid was not widened, to avoid fitting dev harder.

**Chunking choice: fixed.** By the pre-declared criterion (dev hybrid R@5) it scored 0.795 against 0.779 for section. With recency the order flips (0.896 vs 0.898). Both gaps are within noise at n = 512, so **the two strategies are indistinguishable here**, and the pre-declared choice stands rather than whichever looks better after the fact.

**Test-set reporting:** all four configurations, scored once in Phase 7.

## Correction (Phase 7): the HNSW index was not always ignored
The EXPLAIN check above was right for typical patients but not for every plan. psycopg switches to server-side prepared statements after 5 executions, and Postgres may then use a **generic plan**. For the largest test chart (person 1036, 777 chunks) the planner sometimes chose the HNSW index. HNSW returns the `ef_search` = 40 nearest chunks across **all** patients *before* the `person_id` filter, so 4 dense queries for that patient returned **zero** chunks. The answer requests then had an empty citation enum and the API rejected them (unbilled), which is how the bug surfaced.

- **Fix:** the HNSW index is dropped and no longer built. No query in this project is global, so it had no use. `build_requests` now raises if retrieval returns nothing, rather than sending an empty context.
- **Impact audit:** every stored test answer's `shown_chunks` was re-derived with index scans disabled (forced exact). All 6,000 answers in the five runs matched, except those 4 dense questions, which were rebuilt and answered after the fix. Re-running the dev retrieval evaluation reproduced the committed `eval/results/dev/` files byte for byte, so Phase 5 tuning was unaffected.
- **Lesson:** filtered vector search with an ANN index is a known pgvector trap (pgvector 0.8's `hnsw.iterative_scan` addresses it). Here, exact search per patient is both correct and fast (about 1 ms).
