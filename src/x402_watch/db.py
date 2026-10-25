"""Local SQLite state and idempotent outbox storage."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Self

from .models import EvidenceSource


class Store:
    def __init__(self, database: Path | str):
        self._database = str(database)
        if self._database != ":memory:":
            path = Path(self._database)
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            previous_umask = os.umask(0o077)
            try:
                self._connection = sqlite3.connect(
                    self._database,
                    timeout=30,
                    check_same_thread=False,
                )
            finally:
                os.umask(previous_umask)
            os.chmod(path, 0o600)
        else:
            self._connection = sqlite3.connect(
                self._database,
                timeout=30,
                check_same_thread=False,
            )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                brief_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                coverage_complete INTEGER NOT NULL DEFAULT 0,
                errors_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS queries (
                query_id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                lane TEXT NOT NULL,
                query_text TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER NOT NULL DEFAULT 0,
                error_code TEXT,
                retrieved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                lane TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                publisher TEXT NOT NULL,
                published_at TEXT,
                retrieved_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                primary_source INTEGER NOT NULL,
                history_status TEXT NOT NULL DEFAULT 'new',
                hailo_relevance TEXT,
                PRIMARY KEY(run_id, source_id),
                UNIQUE(run_id, canonical_url)
            );
            CREATE TABLE IF NOT EXISTS briefs (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                brief_date TEXT NOT NULL,
                markdown TEXT NOT NULL,
                validation_status TEXT NOT NULL,
                publish_status TEXT NOT NULL DEFAULT 'not_requested',
                github_commit TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS publish_outbox (
                run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
                path TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sources_date
                ON sources(run_id, lane);
            CREATE INDEX IF NOT EXISTS idx_runs_date
                ON runs(brief_date, status);
            """
        )
        self._connection.commit()

    def start_run(self, run_id: str, brief_date: str, started_at: str) -> None:
        self._connection.execute(
            """
            INSERT INTO runs (run_id, brief_date, started_at, status)
            VALUES (?, ?, ?, 'running')
            """,
            (run_id, brief_date, started_at),
        )
        self._connection.commit()

    def record_query(
        self,
        run_id: str,
        lane: str,
        query: str,
        status: str,
        result_count: int,
        retrieved_at: str,
        error_code: str | None = None,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO queries
                (run_id, lane, query_text, status, result_count, error_code, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, lane, query, status, result_count, error_code, retrieved_at),
        )
        self._connection.commit()

    def save_source(self, run_id: str, source: EvidenceSource) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO sources (
                source_id, run_id, lane, title, url, canonical_url, publisher,
                published_at, retrieved_at, content_hash, excerpt, primary_source,
                history_status, hailo_relevance
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.source_id,
                run_id,
                source.lane.value,
                source.title,
                source.url,
                source.canonical_url,
                source.publisher,
                source.published_at,
                source.retrieved_at,
                source.content_hash,
                source.excerpt,
                int(source.primary_source),
                source.history_status,
                source.hailo_relevance,
            ),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def has_prior_complete_run(self, run_id: str, brief_date: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1 FROM runs
            WHERE run_id != ? AND brief_date <= ? AND status = 'complete'
              AND coverage_complete = 1
            LIMIT 1
            """,
            (run_id, brief_date),
        ).fetchone()
        return row is not None

    def prior_source_hash(
        self,
        run_id: str,
        brief_date: str,
        canonical_url: str,
    ) -> str | None:
        row = self._connection.execute(
            """
            SELECT s.content_hash
            FROM sources AS s
            JOIN runs AS r ON r.run_id = s.run_id
            WHERE s.run_id != ? AND s.canonical_url = ?
              AND r.brief_date <= ? AND r.status = 'complete'
              AND r.coverage_complete = 1
            ORDER BY r.brief_date DESC, r.completed_at DESC
            LIMIT 1
            """,
            (run_id, canonical_url, brief_date),
        ).fetchone()
        return str(row["content_hash"]) if row is not None else None

    def finish_run(
        self,
        run_id: str,
        completed_at: str,
        status: str,
        coverage_complete: bool,
        errors: list[str],
    ) -> None:
        self._connection.execute(
            """
            UPDATE runs
            SET completed_at = ?, status = ?, coverage_complete = ?, errors_json = ?
            WHERE run_id = ?
            """,
            (
                completed_at,
                status,
                int(coverage_complete),
                json.dumps(errors),
                run_id,
            ),
        )
        self._connection.commit()

    def save_brief(
        self,
        run_id: str,
        brief_date: str,
        markdown: str,
        validation_status: str,
        created_at: str,
        publish_requested: bool = False,
    ) -> None:
        publish_status = "pending" if publish_requested else "not_requested"
        path = f"briefs/{brief_date}.md"
        self._connection.execute(
            """
            UPDATE briefs
            SET publish_status = 'superseded'
            WHERE run_id IN (
                SELECT run_id FROM publish_outbox
                WHERE path = ? AND status = 'pending' AND run_id != ?
            )
            """,
            (path, run_id),
        )
        self._connection.execute(
            """
            UPDATE publish_outbox
            SET status = 'superseded',
                last_error = 'A newer validated brief exists for this date'
            WHERE path = ? AND status = 'pending' AND run_id != ?
            """,
            (path, run_id),
        )
        self._connection.execute(
            """
            INSERT OR REPLACE INTO briefs
                (run_id, brief_date, markdown, validation_status, publish_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, brief_date, markdown, validation_status, publish_status, created_at),
        )
        self._connection.execute(
            """
            INSERT OR REPLACE INTO publish_outbox (run_id, path, content, status)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, path, markdown, publish_status),
        )
        self._connection.commit()

    def update_publish_status(
        self,
        run_id: str,
        status: str,
        commit: str | None = None,
        error: str | None = None,
        outbox_status: str | None = None,
    ) -> None:
        self._connection.execute(
            "UPDATE briefs SET publish_status = ?, github_commit = ? WHERE run_id = ?",
            (status, commit, run_id),
        )
        self._connection.execute(
            """
            UPDATE publish_outbox
            SET status = ?, attempts = attempts + 1, last_error = ?
            WHERE run_id = ?
            """,
            (outbox_status or status, error, run_id),
        )
        self._connection.commit()

    def pending_outbox(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT o.run_id, o.path, o.content, o.attempts, b.brief_date
            FROM publish_outbox AS o
            JOIN briefs AS b ON b.run_id = o.run_id
            WHERE o.status = 'pending' AND b.validation_status = 'passed'
            ORDER BY b.brief_date, o.run_id
            """
        )
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = ["Store"]
