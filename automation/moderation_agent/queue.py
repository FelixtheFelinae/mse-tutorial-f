from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


SCHEMA = """
CREATE TABLE IF NOT EXISTS moderation_jobs (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    body TEXT NOT NULL,
    attachments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moderation_jobs_status
ON moderation_jobs(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_moderation_jobs_content_hash
ON moderation_jobs(content_hash);
"""


class ModerationQueue:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.database_path.parent, 0o700)
        except OSError:
            pass
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
        try:
            os.chmod(self.database_path, 0o600)
        except OSError:
            pass

    def add_submission(
        self,
        *,
        message_id: str,
        sender: str,
        subject: str,
        content_hash: str,
        body: str,
        attachments: Iterable[Dict[str, object]],
    ) -> Tuple[str, bool]:
        now = datetime.now(timezone.utc).isoformat()
        job_id = str(uuid.uuid4())
        serialized_attachments = json.dumps(
            list(attachments), ensure_ascii=False, sort_keys=True
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM moderation_jobs
                WHERE message_id = ? OR content_hash = ?
                """,
                (message_id, content_hash),
            ).fetchone()
            if existing:
                return str(existing["id"]), False
            connection.execute(
                """
                INSERT INTO moderation_jobs (
                    id, message_id, sender, subject, content_hash, body,
                    attachments_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'RECEIVED', ?, ?)
                """,
                (
                    job_id,
                    message_id,
                    sender,
                    subject,
                    content_hash,
                    body,
                    serialized_attachments,
                    now,
                    now,
                ),
            )
        return job_id, True

    def list_jobs(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, message_id, sender, subject, content_hash, status,
                       created_at, updated_at, attachments_json
                FROM moderation_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        jobs: List[Dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["attachments"] = json.loads(str(item.pop("attachments_json")))
            jobs.append(item)
        return jobs
