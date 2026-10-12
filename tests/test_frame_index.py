"""Tests for migration 003: an expression index on pulse_events for
context->>'via.frame', the key every per-project Via question filters on.

Mirrors the Postgres-gated pattern already used by tests/test_collector.py:
skips if PULSEWISE_TEST_DATABASE_URL is not reachable, otherwise applies
migrations against it and inspects pg_indexes / EXPLAIN directly.
"""
from __future__ import annotations

import os

import psycopg
import pytest

from ingestion.db import apply_migrations

TEST_DB_URL = os.getenv(
    "PULSEWISE_TEST_DATABASE_URL",
    "postgresql://maneeshmenon@localhost:5432/pulsewise_test",
)


def _pg_reachable(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(TEST_DB_URL),
    reason="Postgres not reachable at PULSEWISE_TEST_DATABASE_URL",
)


@pytest.fixture(scope="module", autouse=True)
def _migrated():
    apply_migrations(TEST_DB_URL)


class TestMigration003FrameIndex:
    def test_migration_003_file_is_applied(self):
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            rows = conn.execute(
                "select version from schema_migrations where version like '003_%'"
            ).fetchall()
        assert rows, "expected a schema_migrations row for a migrations/003_*.sql file"

    def test_index_exists_on_via_frame_expression(self):
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            idx = conn.execute(
                "select indexname, indexdef from pg_indexes where tablename = 'pulse_events'"
            ).fetchall()
        frame_idx = [(n, d) for n, d in idx if "context ->> 'via.frame'" in d]
        assert frame_idx, f"no index on (context ->> 'via.frame'); indexes: {idx}"

    def test_planner_uses_the_index_for_a_via_frame_filter(self):
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            idx = conn.execute(
                "select indexname, indexdef from pg_indexes where tablename = 'pulse_events'"
            ).fetchall()
            frame_idx_names = [n for n, d in idx if "context ->> 'via.frame'" in d]
            assert frame_idx_names, "no via.frame index to check the planner against"

            conn.execute("set enable_seqscan = off")
            plan = "\n".join(
                r[0]
                for r in conn.execute(
                    "explain select count(*) from pulse_events "
                    "where context->>'via.frame' = 'x'"
                ).fetchall()
            )
        assert any(name in plan for name in frame_idx_names), (
            f"planner did not use {frame_idx_names} for a via.frame filter: {plan}"
        )

    def test_rerunning_apply_migrations_applies_nothing_new(self):
        applied_again = apply_migrations(TEST_DB_URL)
        assert applied_again == []
