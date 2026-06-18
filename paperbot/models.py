from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def matches_keywords(paper: "PaperCandidate", keywords: tuple[str, ...]) -> bool:
    haystack = f"{paper.title}\n{paper.abstract}".lower()
    for keyword in keywords:
        token = keyword.strip().lower()
        if token and re.search(rf"(?<![a-z0-9]){re.escape(token)}(?:s)?(?![a-z0-9])", haystack):
            return True
    return False


class PaperCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    published_at: str = ""
    abstract: str = ""
    doi: str = ""
    arxiv_id: str = ""
    entry_url: str
    pdf_url: str = ""
    source: str

    @property
    def canonical_key(self) -> str:
        digest = hashlib.sha256(normalize_title(self.title).encode()).hexdigest()
        return f"title:{digest}"

    @property
    def year(self) -> int:
        match = re.search(r"\b(19|20)\d{2}\b", self.published_at)
        return int(match.group()) if match else date.today().year


class PaperSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    paper_url: str
    authors: list[str]
    venue: str
    overview: list[str]
    problem: list[str]
    solution_architecture: list[str]
    results: list[str]
    comparisons: list[str]
    future_work_explicit: list[str]
    future_work_inferred: list[str]

    @classmethod
    def json_schema_for_api(cls) -> dict[str, Any]:
        schema = cls.model_json_schema()
        schema.pop("$defs", None)
        return schema

