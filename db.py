# db.py
import sqlite3
import json
from datetime import datetime

DB_FILE = "queue.db"

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE, timeout=10)  # 10s timeout for locks
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging for better concurrency
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    """Initializes the database schema and default config."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL,
                run_at TEXT, -- ISO-8601 timestamp for backoff
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Set default configuration
        conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('max_retries', '3')")
        conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('backoff_base', '2')")
        conn.commit()

def get_config_value(key):
    """Gets a configuration value by key."""
    with get_db_connection() as conn:
        row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
        return row['value'] if row else None

def set_config_value(key, value):
    """Sets a configuration value."""
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()

def create_job(job_data):
    """Enqueues a new job."""
    now = datetime.utcnow().isoformat()
    default_retries = get_config_value('max_retries')
    
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, command, state, max_retries, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, ?, ?)
            """,
            (
                job_data['id'],
                job_data['command'],
                job_data.get('max_retries', default_retries),
                now,
                now,
            ),
        )
        conn.commit()

def fetch_job_atomically():
    """
    Atomically fetches the next pending job and marks it as 'processing'.
    This is the core locking mechanism.
    """
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        # Start an IMMEDIATE transaction. This locks the database for writing.
        # No other worker can start its own transaction until this one is committed.
        conn.execute("BEGIN IMMEDIATE")
        try:
            job_row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'pending'
                  AND (run_at IS NULL OR run_at <= ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()

            if job_row:
                job_id = job_row['id']
                conn.execute(
                    "UPDATE jobs SET state = 'processing', updated_at = ? WHERE id = ?",
                    (now, job_id),
                )
                conn.commit()
                return dict(job_row)  # Return the job as a dictionary
            else:
                conn.commit()  # Nothing to do, just commit (release lock)
                return None
        except sqlite3.OperationalError as e:
            # Handle "database is locked" gracefully if it ever happens
            print(f"Database lock error: {e}")
            conn.rollback()
            return None
        except Exception as e:
            conn.rollback()
            raise e

def update_job_state(job_id, state):
    """Updates a job's state (e.g., to 'completed' or 'dead')."""
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (state, now, job_id),
        )
        conn.commit()

def update_job_for_retry(job_id, attempts, run_at):
    """Schedules a job for retry with backoff."""
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET state = 'pending', attempts = ?, run_at = ?, updated_at = ? WHERE id = ?",
            (attempts, run_at.isoformat(), now, job_id),
        )
        conn.commit()

def get_jobs_by_state(state):
    """Lists all jobs with a given state."""
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM jobs WHERE state = ? ORDER BY created_at", (state,)).fetchall()
        return [dict(row) for row in rows]

def get_status_summary():
    """Gets a count of jobs by state."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) as count FROM jobs GROUP BY state"
        ).fetchall()
        return {row['state']: row['count'] for row in rows}

def reset_job_for_retry(job_id):
    """Resets a 'dead' job to 'pending' from the DLQ."""
    now = datetime.utcnow().isoformat()
    with get_db_connection() as conn:
        # We must use a cursor to get the 'rowcount'
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET state = 'pending', attempts = 0, run_at = NULL, updated_at = ? WHERE id = ? AND state = 'dead'",
            (now, job_id),
        )
        conn.commit()
        # Check how many rows were changed by the cursor
        return cursor.rowcount > 0
