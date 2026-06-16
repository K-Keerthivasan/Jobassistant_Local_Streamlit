"""Generated-application store (SQLite, table ``runs``).

A "run" is one generated application — resume + cover letter + email + QA +
target — produced by ``pipeline.run``. Nothing is written to disk: the full
bundle lives here and PDFs/DOCX are rendered on demand at download time.
"""

from __future__ import annotations

import json

from . import db


def save_run(bundle: dict) -> dict:
    """Insert or replace a run (keyed by ``run_id``). Returns the bundle."""
    with db.connect() as conn:
        db._upsert_run_row(conn, bundle)
    return bundle


def get_run(run_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def list_runs() -> list[dict]:
    """Summaries of every run, newest first (for the /outputs listing)."""
    with db.connect() as conn:
        cur = conn.execute(
            """SELECT run_id, company, title, persona, created_at
               FROM runs ORDER BY created_at DESC"""
        )
        return [
            {
                "folder": r["run_id"],      # back-compat: the UI keys runs by "folder"
                "run_id": r["run_id"],
                "company": r["company"],
                "title": r["title"],
                "persona": r["persona"],
                "created_at": r["created_at"],
                "has_pdf": True,            # always renderable on demand
            }
            for r in cur.fetchall()
        ]


def update_run(run_id: str, **patch) -> dict | None:
    """Shallow-merge ``patch`` into a stored run's bundle (e.g. an applied
    rewrite of the resume/cover_letter/qa). Returns the updated bundle."""
    bundle = get_run(run_id)
    if bundle is None:
        return None
    bundle.update(patch)
    return save_run(bundle)


def delete_run(run_id: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        return cur.rowcount > 0
