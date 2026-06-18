from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from paperbot.config import Settings
from paperbot.db import Database
from paperbot.http import make_client
from paperbot.service import PaperBot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperbot")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="project root containing .env (default: current directory)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="discover, summarize, and send one paper")
    subparsers.add_parser("dry-run", help="run the pipeline and print without sending")
    subparsers.add_parser("retry", help="resend the oldest summarized paper")
    health = subparsers.add_parser("healthcheck", help="validate local and API configuration")
    health.add_argument("--online", action="store_true", help="also call Gemini and LINE APIs")
    return parser


def healthcheck(settings: Settings, online: bool) -> int:
    errors = settings.validate(require_line=True)
    if shutil.which("pdftotext") is None:
        errors.append("pdftotext is not installed")
    try:
        db = Database(settings.db_path)
        db.close()
    except Exception as exc:
        errors.append(f"SQLite check failed: {exc}")

    if online and not errors:
        client = make_client(settings.contact_email)
        try:
            gemini = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": settings.gemini_api_key},
            )
            if gemini.is_error:
                errors.append(f"Gemini API check failed: HTTP {gemini.status_code}")
            line = client.get(
                "https://api.line.me/v2/bot/info",
                headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
            )
            if line.is_error:
                errors.append(f"LINE API check failed: HTTP {line.status_code}")
        except Exception as exc:
            errors.append(f"online check failed: {exc}")
        finally:
            client.close()

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: configuration, pdftotext, and SQLite are ready")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings.load(args.root)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        if args.command == "healthcheck":
            code = healthcheck(settings, args.online)
        elif args.command == "retry":
            print(PaperBot(settings).retry())
            code = 0
        elif args.command == "dry-run":
            print(PaperBot(settings).run(dry_run=True))
            code = 0
        else:
            print(PaperBot(settings).run())
            code = 0
    except Exception as exc:
        logging.getLogger(__name__).exception("paperbot failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)

