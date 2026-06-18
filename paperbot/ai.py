from __future__ import annotations

import json
import logging
import time

import httpx
from pydantic import ValidationError

from paperbot.models import PaperCandidate, PaperSummary

LOG = logging.getLogger(__name__)
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class AllModelsFailed(RuntimeError):
    pass


class GeminiPool:
    def __init__(
        self,
        client: httpx.Client,
        api_key: str,
        models: tuple[str, ...],
        attempts_per_model: int = 3,
    ):
        self.client = client
        self.api_key = api_key
        self.models = models
        self.attempts_per_model = attempts_per_model

    def summarize(self, paper: PaperCandidate, text: str) -> tuple[PaperSummary, str]:
        failures: list[str] = []
        for model in self.models:
            for attempt in range(1, self.attempts_per_model + 1):
                try:
                    summary = self._call(model, paper, text)
                    return summary, model
                except Exception as exc:
                    failures.append(f"{model} attempt {attempt}: {exc}")
                    LOG.warning("Gemini model %s attempt %d failed: %s", model, attempt, exc)
                    if attempt < self.attempts_per_model:
                        time.sleep(min(2 ** (attempt - 1), 4))
        raise AllModelsFailed("; ".join(failures))

    def _call(self, model: str, paper: PaperCandidate, text: str) -> PaperSummary:
        prompt = self._prompt(paper, text)
        response = self.client.post(
            GEMINI_API.format(model=model),
            headers={"x-goog-api-key": self.api_key},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": PaperSummary.json_schema_for_api(),
                },
            },
            timeout=120.0,
        )
        response.raise_for_status()
        body = response.json()
        try:
            parts = body["candidates"][0]["content"]["parts"]
            raw = "".join(part.get("text", "") for part in parts)
            return PaperSummary.model_validate(json.loads(raw))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"invalid structured model response: {exc}") from exc

    @staticmethod
    def _prompt(paper: PaperCandidate, text: str) -> str:
        metadata = json.dumps(
            {
                "title": paper.title,
                "authors": paper.authors,
                "venue": paper.venue or "未確認",
                "paper_url": paper.entry_url,
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
            },
            ensure_ascii=False,
        )
        return f"""
你是電腦架構研究員。請只根據下方 metadata 與論文全文，以繁體中文產生精確摘要。

規則：
1. 每個內容欄位使用簡短條列句，不得虛構數字、架構、比較對象或作者主張。
2. comparisons 僅整理本文實驗或 related work 明確比較的工作；沒有就填「論文未提供可驗證的直接比較」。
3. future_work_explicit 僅放作者明確陳述的未來工作；沒有就填「作者未明確提出 future work」。
4. future_work_inferred 可提出合理延伸，但每一點必須以「推論：」開頭。
5. title、paper_url、authors、venue 優先使用 metadata；venue 未確認時才由全文判斷。
6. 保留重要量化成果及基準名稱。

METADATA:
{metadata}

PAPER TEXT:
{text}
""".strip()

