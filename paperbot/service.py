from __future__ import annotations

import fcntl
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from paperbot.ai import AllModelsFailed, GeminiPool
from paperbot.config import Settings
from paperbot.db import Database
from paperbot.http import make_client
from paperbot.line import LineMessenger, format_digest
from paperbot.papers import PaperReader, PaperUnavailable
from paperbot.sources import discover_all

LOG = logging.getLogger(__name__)


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def process_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning("another paperbot process is already running") from exc
        yield


class PaperBot:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, dry_run: bool = False) -> str:
        errors = self.settings.validate(require_line=not dry_run)
        if errors:
            raise ValueError("; ".join(errors))

        with process_lock(self.settings.lock_path):
            client = make_client(self.settings.contact_email)
            db = Database(self.settings.db_path)
            messenger = LineMessenger(
                client,
                self.settings.line_channel_access_token,
                self.settings.line_user_id,
            )
            try:
                with db.run():
                    if not dry_run:
                        pending = db.pending_summary()
                        if pending:
                            paper, summary, model = pending
                            messenger.send(format_digest(paper, summary, model))
                            db.mark_sent(paper.id or 0)
                            return f"resent summarized paper: {paper.title}"

                    source_failures: list[str] = []
                    discovered = 0
                    for source, result in discover_all(
                        client,
                        self.settings.venues,
                        self.settings.contact_email,
                        self.settings.ieee_api_key,
                        self.settings.preferred_keywords,
                    ):
                        if isinstance(result, Exception):
                            source_failures.append(f"{source}: {result}")
                            continue
                        for paper in result:
                            if paper.title and paper.entry_url:
                                paper.id = db.upsert(paper)
                                discovered += 1

                    candidates = db.candidates(
                        self.settings.venues,
                        self.settings.preferred_keywords,
                        self.settings.max_candidates,
                    )
                    if not candidates:
                        detail = "沒有找到尚未推送的候選論文"
                        if source_failures:
                            detail += "\n來源錯誤：" + " | ".join(source_failures)
                        if not dry_run:
                            messenger.notify_error(detail)
                        raise RuntimeError(detail)

                    reader = PaperReader(
                        client,
                        self.settings.venues,
                        self.settings.max_pdf_mb,
                        self.settings.max_paper_chars,
                    )
                    pool = GeminiPool(
                        client,
                        self.settings.gemini_api_key,
                        self.settings.gemini_models,
                    )
                    pdf_failures: list[str] = []
                    for paper in candidates:
                        try:
                            text = reader.extract(paper)
                        except PaperUnavailable as exc:
                            detail = str(exc)
                            pdf_failures.append(f"{paper.title}: {detail}")
                            if paper.id:
                                db.save_failure(paper.id, detail)
                            continue

                        try:
                            summary, model = pool.summarize(paper, text)
                        except AllModelsFailed as exc:
                            if not dry_run:
                                self._notify_safely(
                                    messenger, f"所有 Gemini 模型皆無法使用：{exc}"
                                )
                            raise

                        messages = format_digest(paper, summary, model)
                        if dry_run:
                            rendered = "\n\n--- LINE MESSAGE ---\n\n".join(messages)
                            return (
                                f"dry-run selected: {paper.title}\n"
                                f"discovered: {discovered}\nmodel: {model}\n\n{rendered}"
                            )

                        if paper.id is None:
                            paper.id = db.upsert(paper)
                        db.save_summary(paper.id, summary, model)
                        messenger.send(messages)
                        db.mark_sent(paper.id)
                        return f"sent: {paper.title} ({model})"

                    detail = "候選論文皆無法取得可解析全文"
                    if pdf_failures:
                        detail += "\n" + "\n".join(pdf_failures[:5])
                    if source_failures:
                        detail += "\n來源錯誤：" + " | ".join(source_failures)
                    if not dry_run:
                        self._notify_safely(messenger, detail)
                    raise RuntimeError(detail)
            finally:
                db.close()
                client.close()

    def retry(self) -> str:
        errors = self.settings.validate(require_line=True)
        if errors:
            raise ValueError("; ".join(errors))
        with process_lock(self.settings.lock_path):
            client = make_client(self.settings.contact_email)
            db = Database(self.settings.db_path)
            try:
                pending = db.pending_summary()
                if not pending:
                    raise RuntimeError("no summarized-but-unsent paper exists")
                paper, summary, model = pending
                LineMessenger(
                    client,
                    self.settings.line_channel_access_token,
                    self.settings.line_user_id,
                ).send(format_digest(paper, summary, model))
                db.mark_sent(paper.id or 0)
                return f"resent: {paper.title}"
            finally:
                db.close()
                client.close()

    @staticmethod
    def _notify_safely(messenger: LineMessenger, detail: str) -> None:
        try:
            messenger.notify_error(detail)
        except Exception:
            LOG.exception("Failed to send LINE error notification")

