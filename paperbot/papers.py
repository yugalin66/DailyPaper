from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

import httpx

from paperbot.models import PaperCandidate, normalize_title
from paperbot.sources import fetch_arxiv

LOG = logging.getLogger(__name__)


class PaperUnavailable(RuntimeError):
    pass


class PaperReader:
    def __init__(
        self,
        client: httpx.Client,
        venues: tuple[str, ...],
        max_pdf_mb: int,
        max_chars: int,
    ):
        self.client = client
        self.venues = venues
        self.max_bytes = max_pdf_mb * 1024 * 1024
        self.max_chars = max_chars

    def extract(self, paper: PaperCandidate) -> str:
        errors: list[str] = []
        for url in self._candidate_urls(paper):
            try:
                pdf = self._download_pdf(url)
                text = self._pdftotext(pdf)
                if len(text.strip()) < 1500:
                    raise PaperUnavailable("PDF contained too little extractable text")
                return text[: self.max_chars]
            except Exception as exc:
                errors.append(f"{url}: {exc}")

        try:
            equivalent = self._find_arxiv_equivalent(paper)
            if equivalent:
                pdf = self._download_pdf(equivalent.pdf_url)
                text = self._pdftotext(pdf)
                if len(text.strip()) >= 1500:
                    return text[: self.max_chars]
        except Exception as exc:
            errors.append(f"arXiv fallback: {exc}")

        detail = "; ".join(errors[-4:]) or "no PDF URL was available"
        raise PaperUnavailable(detail)

    def _candidate_urls(self, paper: PaperCandidate) -> list[str]:
        urls: list[str] = []
        if paper.pdf_url:
            urls.append(paper.pdf_url)
        if paper.doi:
            doi_url = f"https://doi.org/{paper.doi}"
            try:
                response = self.client.get(
                    doi_url,
                    headers={"Accept": "application/pdf, text/html;q=0.9"},
                )
                response.raise_for_status()
                if self._is_pdf(response):
                    urls.append(str(response.url))
                else:
                    urls.extend(self._pdf_links(response.text, str(response.url)))
            except Exception as exc:
                LOG.debug("DOI resolution failed for %s: %s", paper.doi, exc)
        if paper.entry_url and paper.entry_url not in urls:
            try:
                response = self.client.get(paper.entry_url)
                response.raise_for_status()
                if self._is_pdf(response):
                    urls.append(str(response.url))
                else:
                    urls.extend(self._pdf_links(response.text, str(response.url)))
            except Exception as exc:
                LOG.debug("Landing page failed for %s: %s", paper.entry_url, exc)
        return list(dict.fromkeys(urls))

    def _download_pdf(self, url: str) -> bytes:
        with self.client.stream("GET", url, headers={"Accept": "application/pdf"}) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise PaperUnavailable("PDF exceeds configured size limit")
                chunks.append(chunk)
        content = b"".join(chunks)
        if not content.lstrip().startswith(b"%PDF"):
            raise PaperUnavailable("response was not a PDF")
        return content

    @staticmethod
    def _pdftotext(content: bytes) -> str:
        with tempfile.TemporaryDirectory(prefix="paperbot-") as directory:
            pdf_path = Path(directory) / "paper.pdf"
            text_path = Path(directory) / "paper.txt"
            pdf_path.write_bytes(content)
            result = subprocess.run(
                ["pdftotext", "-layout", str(pdf_path), str(text_path)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                raise PaperUnavailable(result.stderr.strip() or "pdftotext failed")
            return text_path.read_text(encoding="utf-8", errors="replace")

    def _find_arxiv_equivalent(self, paper: PaperCandidate) -> PaperCandidate | None:
        words = normalize_title(paper.title).split()
        if not words:
            return None
        query_title = " ".join(words[:15]).replace('"', "")
        matches = fetch_arxiv(
            self.client,
            self.venues,
            max_results=10,
            query=f'ti:"{query_title}"',
        )
        target = normalize_title(paper.title)
        for match in matches:
            score = SequenceMatcher(None, target, normalize_title(match.title)).ratio()
            if score >= 0.9:
                return match
        return None

    @staticmethod
    def _is_pdf(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        return "application/pdf" in content_type or response.content.lstrip().startswith(b"%PDF")

    @staticmethod
    def _pdf_links(html: str, base_url: str) -> list[str]:
        patterns = (
            r'<meta[^>]+(?:name|property)=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']citation_pdf_url["\']',
            r'<a[^>]+href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        )
        links: list[str] = []
        for pattern in patterns:
            links.extend(
                urljoin(base_url, unescape(match))
                for match in re.findall(pattern, html, flags=re.I)
            )
        return links

