"""Load OHDSI Athena vocabulary files into the `vocab` schema.

Athena ships tab-delimited files with a .csv extension. Concept names contain literal
double quotes (e.g. 5" gauze), so CSV quoting is disabled by setting the quote character
to a byte that never occurs. Dates are YYYYMMDD, which Postgres parses as dates directly.

Only the tables this project uses are loaded: the core v5.4 vocabulary tables, minus
CONCEPT_SYNONYM, DRUG_STRENGTH and the newer metadata files (see ADR-0006).
The load is skipped when the same release, with identical file sizes, is already loaded.
"""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg

# Column types follow OMOP CDM v5.4, except text in place of varchar(n): Athena names
# can exceed the official widths, and Postgres stores text and varchar identically.
TABLES: dict[str, str] = {
    "concept": """
        concept_id integer NOT NULL, concept_name text NOT NULL, domain_id text NOT NULL,
        vocabulary_id text NOT NULL, concept_class_id text NOT NULL, standard_concept text,
        concept_code text NOT NULL, valid_start_date date NOT NULL, valid_end_date date NOT NULL,
        invalid_reason text""",
    "vocabulary": """
        vocabulary_id text NOT NULL, vocabulary_name text NOT NULL, vocabulary_reference text,
        vocabulary_version text, vocabulary_concept_id integer NOT NULL""",
    "domain": """
        domain_id text NOT NULL, domain_name text NOT NULL, domain_concept_id integer NOT NULL""",
    "concept_class": """
        concept_class_id text NOT NULL, concept_class_name text NOT NULL,
        concept_class_concept_id integer NOT NULL""",
    "relationship": """
        relationship_id text NOT NULL, relationship_name text NOT NULL,
        is_hierarchical text NOT NULL, defines_ancestry text NOT NULL,
        reverse_relationship_id text NOT NULL, relationship_concept_id integer NOT NULL""",
    "concept_relationship": """
        concept_id_1 integer NOT NULL, concept_id_2 integer NOT NULL, relationship_id text NOT NULL,
        valid_start_date date NOT NULL, valid_end_date date NOT NULL, invalid_reason text""",
    "concept_ancestor": """
        ancestor_concept_id integer NOT NULL, descendant_concept_id integer NOT NULL,
        min_levels_of_separation integer NOT NULL, max_levels_of_separation integer NOT NULL""",
}

INDEXES = [
    "ALTER TABLE vocab.concept ADD PRIMARY KEY (concept_id)",
    "CREATE INDEX ON vocab.concept (vocabulary_id, concept_code)",
    "CREATE INDEX ON vocab.concept_relationship (concept_id_1, relationship_id)",
    "CREATE INDEX ON vocab.concept_ancestor (ancestor_concept_id)",
    "CREATE INDEX ON vocab.concept_ancestor (descendant_concept_id)",
]

COPY_OPTIONS = "(FORMAT csv, DELIMITER E'\\t', HEADER true, QUOTE E'\\x01', ENCODING 'UTF8')"
CHUNK = 8 << 20


def release(vocab_dir: Path) -> str:
    """The Athena release string, from the special 'None' row of VOCABULARY.csv."""
    with (vocab_dir / "VOCABULARY.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["vocabulary_id"] == "None":
                return row["vocabulary_version"]
    raise ValueError("VOCABULARY.csv has no 'None' row; not an Athena export?")


def signature(vocab_dir: Path) -> str:
    sizes = ",".join(f"{t}:{(vocab_dir / f'{t.upper()}.csv').stat().st_size}" for t in TABLES)
    return f"{release(vocab_dir)}|{sizes}"


def loaded_signature(conn: psycopg.Connection) -> str | None:
    conn.execute("CREATE TABLE IF NOT EXISTS vocab.load_info (signature text NOT NULL)")
    row = conn.execute("SELECT signature FROM vocab.load_info").fetchone()
    return row[0] if row else None


def load(conn: psycopg.Connection, vocab_dir: Path, force: bool = False) -> dict:
    missing = [f"{t.upper()}.csv" for t in TABLES if not (vocab_dir / f"{t.upper()}.csv").exists()]
    if missing:
        raise FileNotFoundError(f"Missing Athena files in {vocab_dir}: {', '.join(missing)}")
    sig = signature(vocab_dir)
    info = {"release": release(vocab_dir), "signature": sig}
    if not force and loaded_signature(conn) == sig:
        conn.commit()
        return {**info, "skipped": True}

    counts = {}
    with conn.transaction():
        for table, columns in TABLES.items():
            conn.execute(f"DROP TABLE IF EXISTS vocab.{table}")
            conn.execute(f"CREATE TABLE vocab.{table} ({columns})")
            with (
                conn.cursor().copy(f"COPY vocab.{table} FROM STDIN {COPY_OPTIONS}") as copy,
                (vocab_dir / f"{table.upper()}.csv").open("rb") as fh,
            ):
                while block := fh.read(CHUNK):
                    copy.write(block)
            counts[table] = conn.execute(f"SELECT count(*) FROM vocab.{table}").fetchone()[0]
        for statement in INDEXES:
            conn.execute(statement)
        conn.execute("DELETE FROM vocab.load_info")
        conn.execute("INSERT INTO vocab.load_info VALUES (%s)", (sig,))
    for table in TABLES:
        conn.execute(f"ANALYZE vocab.{table}")
    conn.commit()
    return {**info, "skipped": False, "rows": counts}
