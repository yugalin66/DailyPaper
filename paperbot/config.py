from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    root: Path
    gemini_api_key: str
    gemini_models: tuple[str, ...]
    line_channel_access_token: str
    line_user_id: str
    contact_email: str
    ieee_api_key: str
    timezone: str
    db_path: Path
    lock_path: Path
    venues: tuple[str, ...]
    preferred_keywords: tuple[str, ...]
    max_candidates: int
    max_pdf_mb: int
    max_paper_chars: int
    log_level: str

    @classmethod
    def load(cls, root: Path | None = None) -> "Settings":
        root = (root or Path.cwd()).resolve()
        load_dotenv(root / ".env")

        def path_value(name: str, default: str) -> Path:
            value = Path(os.getenv(name, default))
            return value if value.is_absolute() else root / value

        return cls(
            root=root,
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_models=_csv(
                "GEMINI_MODELS",
                "gemini-3-flash-preview,gemini-3.5-flash,gemini-2.5-flash",
            ),
            line_channel_access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""),
            line_user_id=os.getenv("LINE_USER_ID", ""),
            contact_email=os.getenv("CONTACT_EMAIL", ""),
            ieee_api_key=os.getenv("IEEE_API_KEY", ""),
            timezone=os.getenv("PAPERBOT_TIMEZONE", "Asia/Taipei"),
            db_path=path_value("PAPERBOT_DB_PATH", "data/paperbot.sqlite3"),
            lock_path=path_value("PAPERBOT_LOCK_PATH", "data/paperbot.lock"),
            venues=_csv("PAPERBOT_VENUES", "ISCA,MICRO,HPCA,ASPLOS"),
            preferred_keywords=_csv("PAPERBOT_PREFERRED_KEYWORDS", "GPU,GPGPU"),
            max_candidates=int(os.getenv("PAPERBOT_MAX_CANDIDATES", "20")),
            max_pdf_mb=int(os.getenv("PAPERBOT_MAX_PDF_MB", "50")),
            max_paper_chars=int(os.getenv("PAPERBOT_MAX_PAPER_CHARS", "60000")),
            log_level=os.getenv("PAPERBOT_LOG_LEVEL", "INFO").upper(),
        )

    def validate(self, require_line: bool = True) -> list[str]:
        errors: list[str] = []
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is not configured")
        if not self.gemini_models:
            errors.append("GEMINI_MODELS is empty")
        if require_line and not self.line_channel_access_token:
            errors.append("LINE_CHANNEL_ACCESS_TOKEN is not configured")
        if require_line and not self.line_user_id:
            errors.append("LINE_USER_ID is not configured")
        if not self.contact_email:
            errors.append("CONTACT_EMAIL is not configured (required for polite API usage)")
        return errors

