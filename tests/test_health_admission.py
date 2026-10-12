"""Phase 1C(m1) — /health reports the database name and the effective product
allowlist, without ever leaking the connection URL."""
import os

import pytest
from fastapi.testclient import TestClient

from ingestion.collector import create_app
from ingestion.db import apply_migrations

TEST_DB_URL = os.getenv(
    "PULSEWISE_TEST_DATABASE_URL",
    "postgresql://maneeshmenon@localhost:5432/pulsewise_test",
)


def _pg_reachable(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(TEST_DB_URL), reason="postgres not reachable"
)


@pytest.fixture(scope="module", autouse=True)
def _migrated():
    apply_migrations(TEST_DB_URL)


@pytest.fixture
def app():
    app = create_app(database_url=TEST_DB_URL, run_migrations=False)
    yield app
    app.state.pool.close()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


class TestHealthAdmission:
    def test_health_ok_includes_existing_keys(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["db"] is True

    def test_health_includes_database_name(self, client):
        r = client.get("/health")
        body = r.json()
        assert body["database"] == "pulsewise_test"

    def test_health_never_leaks_url(self, client):
        r = client.get("/health")
        assert "postgresql://" not in r.text
        assert "@" not in r.text

    def test_health_default_products(self, client, monkeypatch):
        monkeypatch.delenv("PULSEWISE_VALID_PRODUCTS", raising=False)
        r = client.get("/health")
        body = r.json()
        assert body["products"] == [
            "agentwise",
            "helmerwise",
            "hopwise",
            "scriptwise",
            "voicewise",
        ]

    def test_health_custom_products(self, monkeypatch):
        monkeypatch.setenv("PULSEWISE_VALID_PRODUCTS", "voicewise,via")
        app = create_app(database_url=TEST_DB_URL, run_migrations=False)
        try:
            with TestClient(app) as c:
                r = c.get("/health")
        finally:
            app.state.pool.close()
        body = r.json()
        assert body["products"] == ["via", "voicewise"]
