from __future__ import annotations

import httpx


def make_client(contact_email: str, timeout: float = 30.0) -> httpx.Client:
    identity = contact_email or "not-configured"
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=15.0),
        headers={
            "User-Agent": f"daily-paper-bot/0.1 (mailto:{identity})",
            "Accept-Encoding": "gzip",
        },
    )

