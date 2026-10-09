import os

import psycopg
import pytest
from psycopg import sql

from rwe import db


def _require_db() -> bool:
    return os.environ.get("RWE_REQUIRE_DB") == "1"


@pytest.fixture(scope="session")
def test_dbname():
    """Integration tests run in their own database (<PGDATABASE>_test), created on demand.

    Tests truncate and reload tables, so they must never touch the pipeline's database.
    """
    try:
        admin = db.connect(connect_timeout=3, autocommit=True)
    except psycopg.OperationalError as exc:
        if _require_db():
            raise
        pytest.skip(f"Postgres not reachable: {exc}")
    with admin:
        name = admin.info.dbname + "_test"
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return name


@pytest.fixture
def db_conn(test_dbname):
    """A connection to the test database. In CI, RWE_REQUIRE_DB=1 turns 'Postgres
    unreachable' from a skip into a failure, so integration tests can't silently vanish."""
    with db.connect(dbname=test_dbname) as conn:
        yield conn
