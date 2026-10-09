"""Postgres connections.

Settings come from the standard libpq environment variables (PGHOST, PGPORT, PGUSER,
PGPASSWORD, PGDATABASE), loaded from .env when present. psycopg, psql, dbt and docker
compose all read the same variables, so there is one source of truth and no credentials
in code.
"""

from __future__ import annotations

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from rwe.config import REPO_ROOT

BOOTSTRAP_SQL = REPO_ROOT / "sql" / "bootstrap.sql"


def connect(**kwargs) -> psycopg.Connection:
    # override=False: variables already set in the shell (e.g. by CI) win over .env.
    load_dotenv(REPO_ROOT / ".env", override=False)
    return psycopg.connect("", **kwargs)


def ensure_database(name: str) -> None:
    """Create database `name` if it does not exist, via the default (PGDATABASE) database."""
    with connect(autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def bootstrap(conn: psycopg.Connection) -> None:
    """Create extensions and non-dbt schemas. Safe to run repeatedly."""
    conn.execute(BOOTSTRAP_SQL.read_text())
    conn.commit()
