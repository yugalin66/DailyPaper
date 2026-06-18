from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from paperbot.models import PaperCandidate, PaperSummary, matches_keywords


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY,
                canonical_key TEXT NOT NULL UNIQUE,
                doi TEXT NOT NULL DEFAULT '',
                arxiv_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL,
                authors_json TEXT NOT NULL,
                venue TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                abstract TEXT NOT NULL DEFAULT '',
                entry_url TEXT NOT NULL,
                pdf_url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                failure_reason TEXT NOT NULL DEFAULT '',
                summary_json TEXT,
                model_used TEXT NOT NULL DEFAULT '',
                sent_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS papers_status_date
                ON papers(status, published_at DESC);
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT ''
            );
            """
        )
        self.connection.commit()

    @contextmanager
    def run(self) -> Iterator[int]:
        cursor = self.connection.execute(
            "INSERT INTO runs(started_at, status) VALUES (?, 'running')", (now_iso(),)
        )
        self.connection.commit()
        run_id = int(cursor.lastrowid)
        try:
            yield run_id
        except Exception as exc:
            self.finish_run(run_id, "failed", str(exc))
            raise
        else:
            self.finish_run(run_id, "success", "")

    def finish_run(self, run_id: int, status: str, detail: str) -> None:
        self.connection.execute(
            "UPDATE runs SET finished_at=?, status=?, detail=? WHERE id=?",
            (now_iso(), status, detail[:2000], run_id),
        )
        self.connection.commit()

    def upsert(self, paper: PaperCandidate) -> int:
        timestamp = now_iso()
        self.connection.execute(
            """
            INSERT INTO papers (
                canonical_key, doi, arxiv_id, title, authors_json, venue,
                published_at, abstract, entry_url, pdf_url, source,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_key) DO UPDATE SET
                doi=CASE WHEN excluded.doi != '' THEN excluded.doi ELSE papers.doi END,
                arxiv_id=CASE WHEN excluded.arxiv_id != '' THEN excluded.arxiv_id ELSE papers.arxiv_id END,
                authors_json=CASE WHEN excluded.authors_json != '[]' THEN excluded.authors_json ELSE papers.authors_json END,
                venue=CASE WHEN excluded.venue != '' THEN excluded.venue ELSE papers.venue END,
                published_at=CASE WHEN excluded.published_at != '' THEN excluded.published_at ELSE papers.published_at END,
                abstract=CASE WHEN excluded.abstract != '' THEN excluded.abstract ELSE papers.abstract END,
                entry_url=excluded.entry_url,
                pdf_url=CASE WHEN excluded.pdf_url != '' THEN excluded.pdf_url ELSE papers.pdf_url END,
                updated_at=excluded.updated_at
            """,
            (
                paper.canonical_key,
                paper.doi,
                paper.arxiv_id,
                paper.title,
                json.dumps(paper.authors, ensure_ascii=False),
                paper.venue,
                paper.published_at,
                paper.abstract,
                paper.entry_url,
                paper.pdf_url,
                paper.source,
                timestamp,
                timestamp,
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM papers WHERE canonical_key=?", (paper.canonical_key,)
        ).fetchone()
        self.connection.commit()
        return int(row["id"])

    def pending_summary(self) -> tuple[PaperCandidate, PaperSummary, str] | None:
        row = self.connection.execute(
            "SELECT * FROM papers WHERE status='summarized' ORDER BY updated_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self._paper(row), PaperSummary.model_validate_json(row["summary_json"]), row["model_used"]

    def candidates(
        self,
        venues: tuple[str, ...],
        preferred_keywords: tuple[str, ...],
        limit: int,
    ) -> list[PaperCandidate]:
        priority = {venue.upper() for venue in venues}
        rows = self.connection.execute(
            """
            SELECT * FROM papers
            WHERE status NOT IN ('sent', 'summarized')
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (max(limit * 10, 200),),
        ).fetchall()
        papers = [self._paper(row) for row in rows]
        groups = (
            [p for p in papers if p.venue.upper() in priority and matches_keywords(p, preferred_keywords)],
            [p for p in papers if p.venue.upper() in priority and not matches_keywords(p, preferred_keywords)],
            [p for p in papers if p.venue.upper() not in priority and matches_keywords(p, preferred_keywords)],
            [p for p in papers if p.venue.upper() not in priority and not matches_keywords(p, preferred_keywords)],
        )
        ordered: list[PaperCandidate] = []
        for group in groups:
            group.sort(key=lambda p: p.published_at, reverse=True)
            ordered.extend(group)
        return ordered[:limit]

    def save_failure(self, paper_id: int, reason: str) -> None:
        self.connection.execute(
            "UPDATE papers SET failure_reason=?, updated_at=? WHERE id=?",
            (reason[:2000], now_iso(), paper_id),
        )
        self.connection.commit()

    def save_summary(self, paper_id: int, summary: PaperSummary, model: str) -> None:
        self.connection.execute(
            """
            UPDATE papers
            SET status='summarized', summary_json=?, model_used=?,
                failure_reason='', updated_at=?
            WHERE id=?
            """,
            (summary.model_dump_json(), model, now_iso(), paper_id),
        )
        self.connection.commit()

    def mark_sent(self, paper_id: int) -> None:
        timestamp = now_iso()
        self.connection.execute(
            "UPDATE papers SET status='sent', sent_at=?, updated_at=? WHERE id=?",
            (timestamp, timestamp, paper_id),
        )
        self.connection.commit()

    @staticmethod
    def _paper(row: sqlite3.Row) -> PaperCandidate:
        return PaperCandidate(
            id=row["id"],
            title=row["title"],
            authors=json.loads(row["authors_json"]),
            venue=row["venue"],
            published_at=row["published_at"],
            abstract=row["abstract"],
            doi=row["doi"],
            arxiv_id=row["arxiv_id"],
            entry_url=row["entry_url"],
            pdf_url=row["pdf_url"],
            source=row["source"],
        )
