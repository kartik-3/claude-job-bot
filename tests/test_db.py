"""Tests for DB layer — deduplication and upsert behaviour."""
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "jobs.sqlite"
    with patch("db.DB_PATH", db_path):
        from db import init_db
        init_db()
        yield db_path


def _sample_job(**overrides) -> dict:
    base = {
        "id": "abc123",
        "company": "Acme",
        "title": "Software Engineer",
        "url": "https://example.com/job/1",
        "apply_url": "https://example.com/job/1/apply",
        "ats": "greenhouse",
        "description": "A great job.",
        "location": "Remote",
        "remote": True,
        "posted_at": "2026-04-01T10:00:00Z",
    }
    return {**base, **overrides}


class TestUpsertDedupe:
    def test_first_insert_returns_true(self, tmp_db):
        with patch("db.DB_PATH", tmp_db):
            from db import upsert_job
            is_new = upsert_job(_sample_job())
        assert is_new is True

    def test_second_insert_returns_false(self, tmp_db):
        with patch("db.DB_PATH", tmp_db):
            from db import upsert_job
            upsert_job(_sample_job())
            is_new = upsert_job(_sample_job())
        assert is_new is False

    def test_no_duplicate_rows_after_two_upserts(self, tmp_db):
        with patch("db.DB_PATH", tmp_db):
            from db import count_jobs, upsert_job
            upsert_job(_sample_job())
            upsert_job(_sample_job())
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE id = 'abc123'").fetchone()[0]
        conn.close()
        assert count == 1

    def test_different_url_creates_new_row(self, tmp_db):
        with patch("db.DB_PATH", tmp_db):
            from db import count_jobs, upsert_job
            upsert_job(_sample_job(id="id1", url="https://example.com/job/1"))
            upsert_job(_sample_job(id="id2", url="https://example.com/job/2"))
        conn = sqlite3.connect(tmp_db)
        count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        conn.close()
        assert count == 2

    def test_upsert_preserves_status_on_rediscovery(self, tmp_db):
        with patch("db.DB_PATH", tmp_db):
            from db import upsert_job
            upsert_job(_sample_job())
            # Simulate status update (e.g. after evaluation)
            conn = sqlite3.connect(tmp_db)
            conn.execute("UPDATE jobs SET status = 'should_apply' WHERE id = 'abc123'")
            conn.commit()
            conn.close()
            # Re-discover the same job
            upsert_job(_sample_job())
        conn = sqlite3.connect(tmp_db)
        row = conn.execute("SELECT status FROM jobs WHERE id = 'abc123'").fetchone()
        conn.close()
        assert row[0] == "should_apply"
