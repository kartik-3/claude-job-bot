import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "jobs.sqlite"

STATUSES = (
    "new", "evaluated", "should_apply", "should_not_apply",
    "tailored", "applied", "needs_manual", "blocked", "error",
    "needs_referral", "asked_referral", "applied_with_referral",
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
    date_added           TEXT,
    discovered_at        TEXT NOT NULL,
    fit_score            INTEGER,
    status               TEXT NOT NULL DEFAULT 'new',
    evaluation_json      TEXT,
    tailored_resume_path TEXT,
    cover_letter_path    TEXT,
    applied_at           TEXT,
    screenshot_path      TEXT,
    notes                TEXT,
    CHECK (status IN (
        'new', 'evaluated', 'should_apply', 'should_not_apply',
        'tailored', 'applied', 'needs_manual', 'blocked', 'error',
        'needs_referral', 'asked_referral', 'applied_with_referral'
    ))
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Incremental schema migrations — safe to run on every startup."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    if "cover_letter_path" not in existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN cover_letter_path TEXT")
    if "screenshot_path" not in existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN screenshot_path TEXT")
    if "date_added" not in existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN date_added TEXT")
        # Backfill from discovered_at for existing rows
        conn.execute("UPDATE jobs SET date_added = discovered_at WHERE date_added IS NULL")

    # Rebuild table when CHECK constraint is missing new status values.
    # SQLite can't ALTER a CHECK constraint — requires table recreation.
    schema_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if schema_row and "needs_referral" not in schema_row[0]:
        cols = ", ".join(row[1] for row in conn.execute("PRAGMA table_info(jobs)"))
        conn.executescript(f"""
            ALTER TABLE jobs RENAME TO _jobs_old;
            {_SCHEMA}
            INSERT INTO jobs ({cols}) SELECT {cols} FROM _jobs_old;
            DROP TABLE _jobs_old;
        """)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
        _migrate(conn)


def upsert_job(job: dict) -> bool:
    """Insert a new job row. Returns True if newly inserted, False if already exists."""
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
                 location, remote, posted_at, date_added, discovered_at)
            VALUES
                (:id, :company, :title, :url, :apply_url, :ats, :description,
                 :location, :remote, :posted_at, :discovered_at, :discovered_at)
            """,
            data,
        )
        return result.rowcount == 1


def count_jobs(status: str | None = None) -> int:
    with get_connection() as conn:
        if status:
            row = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0]


def get_company_stats() -> list[dict]:
    """Return per-company job counts, sorted by total jobs descending."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                company,
                ats,
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'should_apply'     THEN 1 ELSE 0 END) AS to_apply,
                SUM(CASE WHEN status = 'should_not_apply' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN status = 'new'              THEN 1 ELSE 0 END) AS pending
            FROM jobs
            GROUP BY company, ats
            ORDER BY total DESC, company
            """
        ).fetchall()
        return [dict(row) for row in rows]


def get_evaluated_jobs(status_filter: str | None = None) -> list[dict]:
    """Return all jobs that have been evaluated, sorted by fit_score descending.

    Pass a status_filter (e.g. 'should_apply') to narrow results.
    Jobs with no fit_score (hard-gated) sort to the bottom.
    """
    with get_connection() as conn:
        if status_filter:
            rows = conn.execute(
                """
                SELECT company, title, status, fit_score, url, apply_url, notes
                FROM jobs
                WHERE status = ?
                ORDER BY fit_score DESC, company, title
                """,
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT company, title, status, fit_score, url, apply_url, notes
                FROM jobs
                WHERE status != 'new'
                ORDER BY fit_score DESC, company, title
                """,
            ).fetchall()
        return [dict(row) for row in rows]


def get_jobs_by_status(status: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ?", (status,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_jobs_for_evaluation(
    companies: list[str] | None = None,
    days: int | None = None,
    locations: list[str] | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """Return status=new jobs with optional filters.

    companies  — include only jobs whose company name contains any of these
                 substrings (case-insensitive)
    days       — include only jobs added within the last N days
    locations  — include only jobs whose location contains any of these
                 substrings (case-insensitive)
    job_id     — return only the single job with this exact ID (ignores status)
    """
    clauses: list[str] = []
    params: list = []

    if job_id:
        clauses.append("id = ?")
        params.append(job_id)
    else:
        clauses.append("status = 'new'")

    if days is not None:
        clauses.append("date(date_added) >= date('now', ?)")
        params.append(f"-{days} days")

    with get_connection() as conn:
        where = " AND ".join(clauses)
        rows = conn.execute(f"SELECT * FROM jobs WHERE {where}", params).fetchall()
        jobs = [dict(row) for row in rows]

    if companies:
        lc = [c.lower() for c in companies]
        jobs = [j for j in jobs if any(f in j["company"].lower() for f in lc)]

    if locations:
        lc = [l.lower() for l in locations]
        jobs = [j for j in jobs if j.get("location") and any(f in j["location"].lower() for f in lc)]

    return jobs


def update_job_tailored(
    job_id: str,
    tailored_resume_path: str | None = None,
    cover_letter_path: str | None = None,
    status: str = "tailored",
    notes: str | None = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET tailored_resume_path = ?,
                cover_letter_path    = ?,
                status               = ?,
                notes                = ?
            WHERE id = ?
            """,
            (tailored_resume_path, cover_letter_path, status, notes, job_id),
        )


def update_job_applied(
    job_id: str,
    status: str,
    notes: str | None = None,
    screenshot_path: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    applied_at = now if status == "applied" else None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status          = ?,
                notes           = ?,
                applied_at      = COALESCE(?, applied_at),
                screenshot_path = COALESCE(?, screenshot_path)
            WHERE id = ?
            """,
            (status, notes, applied_at, screenshot_path, job_id),
        )


def update_job_evaluation(
    job_id: str,
    fit_score: int | None,
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
