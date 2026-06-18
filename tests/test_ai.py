import json

import httpx

from paperbot.ai import GeminiPool
from paperbot.models import PaperCandidate


def test_gemini_pool_falls_back_after_retries(monkeypatch):
    calls = []
    summary = {
        "title": "Paper",
        "paper_url": "https://example.com",
        "authors": ["Author"],
        "venue": "ISCA",
        "overview": ["overview"],
        "problem": ["problem"],
        "solution_architecture": ["solution"],
        "results": ["result"],
        "comparisons": ["comparison"],
        "future_work_explicit": ["none"],
        "future_work_inferred": ["推論：extension"],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "model-one" in request.url.path:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(summary)}]}}]},
        )

    monkeypatch.setattr("paperbot.ai.time.sleep", lambda _: None)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pool = GeminiPool(client, "key", ("model-one", "model-two"))
    paper = PaperCandidate(
        title="Paper", entry_url="https://example.com", source="test"
    )
    result, model = pool.summarize(paper, "paper body")
    assert result.title == "Paper"
    assert model == "model-two"
    assert len([path for path in calls if "model-one" in path]) == 3
    client.close()
