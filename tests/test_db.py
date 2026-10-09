import pytest

from rwe import db

pytestmark = pytest.mark.db


def test_bootstrap_is_idempotent(db_conn):
    db.bootstrap(db_conn)
    db.bootstrap(db_conn)
    schemas = {
        row[0]
        for row in db_conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    }
    assert {"raw", "vocab"} <= schemas


def test_pgvector_is_available(db_conn):
    db.bootstrap(db_conn)
    distance = db_conn.execute("SELECT '[1,0]'::vector <=> '[0,1]'::vector").fetchone()[0]
    assert distance == pytest.approx(1.0)  # cosine distance of orthogonal vectors
