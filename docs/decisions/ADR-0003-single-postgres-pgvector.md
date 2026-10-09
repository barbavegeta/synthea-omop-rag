# ADR-0003: One PostgreSQL instance, with pgvector, for everything

**Status:** accepted

## Context
The project stores raw FHIR, OHDSI vocabularies, the OMOP CDM, notes, embeddings, evaluation ground truth and an LLM spend ledger.

## Options
1. **Postgres + pgvector** for everything.
2. Postgres for relational data plus a dedicated vector database (Qdrant, Chroma, ...).

## Decision
Option 1. Notes, chunks, vectors and ground truth sit in the same database as the CDM, so evaluation joins (chunk → note → visit → person → gold answer) are plain SQL, and one transactional system is all there is to run. At the expected scale (about 10⁵ chunks of 384-d vectors) pgvector with an HNSW index is well within its comfort zone.

## Consequences
- A dedicated vector database would offer more ANN tuning and horizontal scale. Neither matters here, and the README says so.
- The Postgres image is `pgvector/pgvector:pg17`, pinned by digest in both compose and CI (pgvector 0.8.7). A tag can be re-pushed; a digest cannot. Host port 5433 avoids clashing with any local Postgres.
- Connection settings use the standard libpq variables (`PGHOST`, ...), shared by psycopg, psql, dbt and docker compose.
