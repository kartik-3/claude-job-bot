import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.sqlite"

STATUSES = (
    "new", "evaluated", "should_apply", "should_not_apply",
    "tailored", "applied", "needs_manual", "blocked", "error",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                   TEXT PRIMARY KEY,
    company              TEXT NOT NULL,
    title                TEXT NOT NULL,
    url                  TEXT NOT NULL,
    apply_url            TEXT,
    ats                  TEXT NOT NULL,
    description          TEXT,
    location             TEXT,
    remote               INTEGER,
    posted_at            TEXT,
    discovered_at        TEXT NOT NULL,
    fit_score            INTEGER,
    status               TEXT NOT NULL DEFAULT 'new',
    evaluation_json      TEXT,
    tailored_resume_path TEXT,
    applied_at           TEXT,
    notes                TEXT,
    CHECK (status IN (
        'new', 'evaluated', 'should_apply', 'should_not_apply',
        'tailored', 'applied', 'needs_manual', 'blocked', 'error'
    ))
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def upsert_job(job: dict) -> bool:
    """Insert or refresh a job row. Returns True if newly inserted."""
    now = datetime.now(timezone.utc).isoformat()
    data = {
        **job,
        "discovered_at": now,
        "remote": int(job["remote"]) if job.get("remote") is not None else None,
    }
    with get_connection() as conn:
        result = conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (id, company, title, url, apply_url, ats, description,
                 location, remote, posted_at, discovered_at, status)
            VALUES
                (:id, :company, :title, :url, :apply_url, :ats, :description,
                 :location, :remote, :posted_at, :discovered_at, 'new')
            """,
            data,
        )
        is_new = result.rowcount == 1
        if not is_new:
            conn.execute(
                "UPDATE jobs SET discovered_at = ? WHERE id = ?",
                (now, job["id"]),
            )
        return is_new


def count_jobs(status: str | None = None) -> int:
    with get_connection() as conn:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0]


def get_jobs_by_status(status: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ?", (status,)
        ).fetchall()
        return [dict(row) for row in rows]


def update_job_evaluation(
    job_id: str,
    fit_score: int,
    status: str,
    evaluation_json: str,
    notes: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET fit_score = ?, status = ?, evaluation_json = ?, notes = ?
            WHERE id = ?
            """,
            (fit_score, status, evaluation_json, notes, job_id),
        )
