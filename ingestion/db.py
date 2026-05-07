"""Postgres connection pool + migration runner for the collector."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import psycopg
from psycopg_pool import ConnectionPool

logger = logging.getLogger("pulsewise.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def make_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    pool = ConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True},
    )
    pool.open(wait=True, timeout=10.0)
    return pool


def apply_migrations(database_url: str) -> list[str]:
    """Apply any pending SQL migrations from migrations/ in lexical order.

    Tracks applied versions in `schema_migrations`. Returns list of applied
    filenames (newly applied this run).
    """
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        return []

    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute("SELECT version FROM schema_migrations;")
            already = {row[0] for row in cur.fetchall()}

            for path in files:
                version = path.name
                if version in already:
                    continue
                sql = path.read_text()
                logger.info("applying migration %s", version)
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s);",
                    (version,),
                )
                applied.append(version)

    return applied


def healthcheck(pool: ConnectionPool) -> bool:
    try:
        with pool.connection(timeout=2.0) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception as exc:
        logger.warning("db healthcheck failed: %s", exc)
        return False
