"""Test helper: point the SQLite store at a throwaway file so tests never touch
data/resume.db, and skip the legacy JSON backfill."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from resume_gen.config import settings
from resume_gen.intake import db


class TempDB:
    def __enter__(self) -> Path:
        self.tmp = Path(tempfile.mkdtemp())
        self._old_db = settings.db_path
        self._old_intake = settings.intake_dir
        self._old_migrate = db._migrate_json_if_needed
        settings.db_path = self.tmp / "test.db"
        settings.intake_dir = self.tmp / "intake"
        db._migrate_json_if_needed = lambda: None
        db._INITIALIZED = False
        return self.tmp

    def __exit__(self, *exc) -> None:
        settings.db_path = self._old_db
        settings.intake_dir = self._old_intake
        db._migrate_json_if_needed = self._old_migrate
        db._INITIALIZED = False
        shutil.rmtree(self.tmp, ignore_errors=True)
