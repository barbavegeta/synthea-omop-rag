-- Idempotent database bootstrap, run by `rwe db-init` at the start of every pipeline run.
-- Schemas owned by dbt (staging, intermediate, cdm, dq) are created by dbt itself.

CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector, used from Phase 5

CREATE SCHEMA IF NOT EXISTS raw;           -- FHIR resources exactly as received (JSONB)
CREATE SCHEMA IF NOT EXISTS vocab;         -- OHDSI Athena vocabulary tables

-- One row per FHIR resource. Lossless: the full resource is kept as JSONB and all
-- field extraction happens in dbt (ADR-0002). patient_id comes from the bundle's
-- single Patient resource, so every row can be joined to its patient without
-- parsing references.
CREATE TABLE IF NOT EXISTS raw.fhir_resource (
    resource_type text  NOT NULL,
    resource_id   text  NOT NULL,
    patient_id    text  NOT NULL,
    bundle_file   text  NOT NULL,
    payload       jsonb NOT NULL,
    PRIMARY KEY (resource_type, resource_id)
);

-- Phase 4: generated notes (exposed to the CDM as cdm.note by dbt) and evaluation ground truth.
CREATE SCHEMA IF NOT EXISTS notes;
CREATE SCHEMA IF NOT EXISTS eval;

CREATE TABLE IF NOT EXISTS notes.generated_note (
    note_id             integer PRIMARY KEY,
    person_id           integer NOT NULL,
    visit_occurrence_id integer NOT NULL,
    note_date           date    NOT NULL,
    note_kind           text    NOT NULL,
    note_title          text    NOT NULL,
    note_text           text    NOT NULL
);

CREATE TABLE IF NOT EXISTS eval.eval_patient (
    person_id integer PRIMARY KEY,
    split     text NOT NULL CHECK (split IN ('dev', 'test'))
);

-- Every statement written into a note, with its exact character span (ADR-0011).
CREATE TABLE IF NOT EXISTS eval.note_fact (
    fact_id     text PRIMARY KEY,
    note_id     integer NOT NULL,
    person_id   integer NOT NULL,
    fact_type   text    NOT NULL,
    label       text    NOT NULL,
    surface     text    NOT NULL,
    span_start  integer NOT NULL,
    span_end    integer NOT NULL,
    polarity    text    NOT NULL,
    temporality text    NOT NULL,
    experiencer text    NOT NULL,
    source      text    NOT NULL,
    concept_id  integer,
    value       text,
    event_date  date,
    abbreviated boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS eval.question (
    question_id    text PRIMARY KEY,
    split          text    NOT NULL,
    person_id      integer NOT NULL,
    template       text    NOT NULL,
    phenomenon     text    NOT NULL,
    question       text    NOT NULL,
    as_of          date    NOT NULL,
    answer         jsonb   NOT NULL,
    gold_fact_ids  text[]  NOT NULL,
    sql_answerable boolean NOT NULL,
    params         jsonb   NOT NULL
);

-- Phase 5: chunks with embeddings (pgvector), and which gold facts each chunk contains.
CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE IF NOT EXISTS rag.chunk (
    chunk_id    text PRIMARY KEY,           -- <strategy>:<note_id>:<n>
    strategy    text    NOT NULL,           -- section | fixed
    note_id     integer NOT NULL,
    person_id   integer NOT NULL,
    note_date   date    NOT NULL,
    section     text    NOT NULL,
    char_start  integer NOT NULL,           -- [char_start, char_end) in the note text
    char_end    integer NOT NULL,
    content     text    NOT NULL,           -- dated header + note slice
    content_sha text    NOT NULL,
    embedding   vector(384),                -- NULL until embedded (indexing is resumable)
    embed_model text
);
CREATE INDEX IF NOT EXISTS chunk_strategy_person ON rag.chunk (strategy, person_id);

CREATE TABLE IF NOT EXISTS rag.chunk_fact (
    chunk_id text NOT NULL,
    fact_id  text NOT NULL,
    PRIMARY KEY (chunk_id, fact_id)
);

-- Phase 6: LLM spend ledger (hard budget cap), response cache, and answers.
CREATE SCHEMA IF NOT EXISTS llm;

-- One row per API call actually made (cache hits cost nothing and add no row).
CREATE TABLE IF NOT EXISTS llm.spend_ledger (
    call_id         bigserial PRIMARY KEY,
    created_at      timestamptz NOT NULL DEFAULT now(),
    provider        text    NOT NULL,
    model_requested text    NOT NULL,
    model_served    text,
    purpose         text    NOT NULL,
    cache_key       text    NOT NULL,
    input_tokens    integer NOT NULL DEFAULT 0,
    output_tokens   integer NOT NULL DEFAULT 0,
    cost_usd        numeric(12, 6) NOT NULL DEFAULT 0,
    status          text    NOT NULL,       -- ok | refusal | max_tokens | error
    request_id      text
);

-- Responses keyed by a hash of the exact request: reruns replay them at $0.
CREATE TABLE IF NOT EXISTS llm.response_cache (
    cache_key  text PRIMARY KEY,
    request    jsonb NOT NULL,
    response   jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Message Batches (50% price, asynchronous). A submitted batch's worst-case cost stays
-- reserved against the cap until it is collected, even across processes.
CREATE TABLE IF NOT EXISTS llm.batch (
    batch_id     text PRIMARY KEY,
    label        text    NOT NULL,
    provider     text    NOT NULL,
    n_requests   integer NOT NULL,
    reserved_usd numeric(12, 6) NOT NULL,
    status       text    NOT NULL,             -- submitted | collected
    created_at   timestamptz NOT NULL DEFAULT now(),
    collected_at timestamptz
);
CREATE TABLE IF NOT EXISTS llm.batch_request (
    batch_id  text NOT NULL,
    cache_key text NOT NULL,                    -- also the batch custom_id
    model     text NOT NULL,
    purpose   text NOT NULL,
    request   jsonb NOT NULL,
    PRIMARY KEY (batch_id, cache_key)
);

-- Phase 6b: rewritten (messier) notes and the facts' spans in them.
CREATE TABLE IF NOT EXISTS notes.rewritten_note (
    note_id      integer PRIMARY KEY,
    provider     text NOT NULL,                 -- anthropic | fake: never mix the two up
    model        text NOT NULL,
    status       text NOT NULL,                 -- ok | rejected | failed
    reason       text NOT NULL,
    note_text    text                           -- NULL unless status = ok
);
-- Upgrade databases created before the provider column (Phase 6b). Their rows can't be
-- attributed to a provider, so they are dropped; `rwe rewrite` rebuilds them from the cache.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'notes' AND table_name = 'rewritten_note'
                     AND column_name = 'provider') THEN
        TRUNCATE notes.rewritten_note;
        ALTER TABLE notes.rewritten_note ADD COLUMN provider text NOT NULL;
    END IF;
END $$;
CREATE TABLE IF NOT EXISTS eval.note_fact_rewritten (
    fact_id    text PRIMARY KEY,
    note_id    integer NOT NULL,
    span_start integer NOT NULL,
    span_end   integer NOT NULL
);

-- One row per (question, run): what the model saw and said, and how it was graded.
CREATE TABLE IF NOT EXISTS eval.answer (
    run_name        text    NOT NULL,
    question_id     text    NOT NULL,
    model           text    NOT NULL,
    effort          text    NOT NULL,
    retrieval_mode  text    NOT NULL,
    shown_chunks    text[]  NOT NULL,       -- chunk ids in the order shown (labels C1..Ck)
    response        jsonb,                  -- parsed structured answer, NULL if unusable
    stop_reason     text,
    cache_key       text,
    correct         boolean,
    grade_detail    jsonb,
    PRIMARY KEY (run_name, question_id)
);

-- One row per loaded bundle file, with its checksum: an audit trail of exactly
-- which input produced the raw layer.
CREATE TABLE IF NOT EXISTS raw.fhir_bundle (
    bundle_file text    PRIMARY KEY,
    sha256      text    NOT NULL,
    patient_id  text    NOT NULL,
    n_resources integer NOT NULL
);
