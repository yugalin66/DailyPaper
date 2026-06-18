# Repository Guidelines

## Project Structure & Module Organization

`paperbot/` contains the Python 3.12 application. The CLI entry point is `paperbot/cli.py`; configuration, HTTP clients, source discovery, persistence, summarization, LINE delivery, and orchestration are separated into focused modules such as `config.py`, `sources.py`, `db.py`, `ai.py`, and `service.py`. Tests live in `tests/` and generally mirror module names (`tests/test_sources.py`, `tests/test_db.py`). `deploy/` contains the systemd user service and timer. Runtime SQLite and lock files belong in `data/` and must not be committed.

## Build, Test, and Development Commands

Create a local environment and install the package in editable mode:

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Useful commands:

- `.venv/bin/pytest` — run the complete test suite quietly.
- `.venv/bin/pytest tests/test_sources.py` — run one test module.
- `.venv/bin/paperbot healthcheck` — validate local configuration, SQLite, and `pdftotext`.
- `.venv/bin/paperbot dry-run` — exercise discovery and Gemini summarization without sending LINE messages. This uses network APIs and quota.
- `.venv/bin/paperbot run` — execute the production delivery flow.

## Coding Style & Naming Conventions

Follow existing Python conventions: four-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for constants. Add type hints to public functions and keep modules focused on one responsibility. Prefer standard-library features and explicit error handling. No formatter or linter is configured, so keep imports grouped, lines readable, and changes consistent with surrounding code.

## Testing Guidelines

Tests use pytest and are discovered under `tests/` via `pyproject.toml`. Name files `test_<module>.py` and test functions `test_<behavior>()`. Keep tests deterministic: mock HTTP calls, sleeping, Gemini, and LINE interactions rather than contacting external services. Add regression tests for bug fixes and cover both success and failure paths.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects such as `Handle arXiv rate-limit fallback`, and keep each commit focused. Before committing, inspect `git diff --cached` and verify that local configuration or credentials are not staged. Pull requests should explain the behavior change, configuration impact, and verification commands. Link related issues and include sanitized logs or sample CLI output when changing operational behavior.

## Security & Configuration

Copy `.env.example` to `.env`; keep `.env.example` limited to empty values or non-secret defaults. Never commit API keys, LINE credentials, LINE user IDs, downloaded PDFs, database files, lock files, logs, or output containing credentials. Preserve the rule that the bot only accesses openly available or institutionally accessible PDFs and does not bypass authentication, paywalls, or CAPTCHAs.

Before publishing changes, review the staged file list and search tracked content for credential-like assignments. Do not print `.env` in logs, test output, issues, pull requests, or assistant responses. If a secret is ever committed, remove it from history and rotate it; deleting it in a later commit is insufficient.

## Operational Files

The checked-in systemd unit assumes the project lives at `/home/yuga/Desktop/PaperBot`. If the deployment path changes, update all three paths in `deploy/paperbot.service`: `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`. Keep the timer timezone and schedule documented in README synchronized with `deploy/paperbot.timer`.
