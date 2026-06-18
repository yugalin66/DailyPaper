from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Iterable

import httpx

from paperbot.models import PaperCandidate

LOG = logging.getLogger(__name__)
ARXIV_API = "https://export.arxiv.org/api/query"
DBLP_API = "https://dblp.org/search/publ/api"
CROSSREF_API = "https://api.crossref.org/works"
IEEE_API = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

VENUE_NAMES = {
    "ISCA": "International Symposium on Computer Architecture",
    "MICRO": "International Symposium on Microarchitecture",
    "HPCA": "High Performance Computer Architecture",
    "ASPLOS": "Architectural Support for Programming Languages and Operating Systems",
}


def detect_venue(text: str, venues: tuple[str, ...]) -> str:
    haystack = re.sub(r"[^A-Z0-9]+", " ", text.upper())
    for venue in venues:
        token = venue.upper()
        if re.search(rf"\b{re.escape(token)}\b", haystack):
            return venue.upper()
        long_name = VENUE_NAMES.get(token, "").upper()
        if long_name and long_name in text.upper():
            return venue.upper()
    return ""


def clean_doi(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    return value.removeprefix("doi:").strip()


def fetch_arxiv(
    client: httpx.Client,
    venues: tuple[str, ...],
    max_results: int = 100,
    query: str = "cat:cs.AR",
) -> list[PaperCandidate]:
    response = client.get(
        ARXIV_API,
        params={
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[PaperCandidate] = []
    for entry in root.findall("a:entry", ns):
        entry_url = _xml_text(entry, "a:id", ns)
        arxiv_id = entry_url.rstrip("/").rsplit("/", 1)[-1]
        comments = _xml_text(entry, "arxiv:comment", ns)
        journal_ref = _xml_text(entry, "arxiv:journal_ref", ns)
        venue = detect_venue(f"{comments} {journal_ref}", venues)
        pdf_url = ""
        for link in entry.findall("a:link", ns):
            if link.attrib.get("type") == "application/pdf" or link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        doi = clean_doi(_xml_text(entry, "arxiv:doi", ns))
        papers.append(
            PaperCandidate(
                title=_collapse(_xml_text(entry, "a:title", ns)),
                authors=[
                    _collapse(_xml_text(author, "a:name", ns))
                    for author in entry.findall("a:author", ns)
                ],
                venue=venue,
                published_at=_xml_text(entry, "a:published", ns),
                abstract=_collapse(_xml_text(entry, "a:summary", ns)),
                doi=doi,
                arxiv_id=arxiv_id,
                entry_url=entry_url,
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                source="arxiv",
            )
        )
    return papers



def fetch_arxiv_preferred(
    client: httpx.Client,
    venues: tuple[str, ...],
    preferred_keywords: tuple[str, ...],
) -> list[PaperCandidate]:
    terms = [keyword.strip() for keyword in preferred_keywords if keyword.strip()]
    preferred: list[PaperCandidate] = []
    preferred_error: Exception | None = None
    if terms:
        keyword_query = " OR ".join(f'all:"{term.replace(chr(34), "")}"' for term in terms)
        try:
            preferred = fetch_arxiv(
                client, venues, max_results=100, query=f"cat:cs.AR AND ({keyword_query})"
            )
        except Exception as exc:
            preferred_error = exc
            LOG.warning("Preferred arXiv query failed: %s", exc)
        time.sleep(3)

    try:
        general = fetch_arxiv(client, venues, max_results=100)
    except Exception:
        if preferred:
            LOG.warning("General arXiv query failed; continuing with preferred results")
            general = []
        else:
            if preferred_error is not None:
                raise preferred_error
            raise

    merged: dict[str, PaperCandidate] = {}
    for paper in preferred + general:
        merged.setdefault(paper.canonical_key, paper)
    return list(merged.values())

def fetch_dblp(
    client: httpx.Client, venues: tuple[str, ...], max_results_per_venue: int = 250
) -> list[PaperCandidate]:
    papers: list[PaperCandidate] = []
    cutoff = date.today().year - 10
    for requested_venue in venues:
        response = client.get(
            DBLP_API,
            params={"q": requested_venue, "h": max_results_per_venue, "format": "json"},
        )
        response.raise_for_status()
        hits = response.json().get("result", {}).get("hits", {}).get("hit", [])
        if isinstance(hits, dict):
            hits = [hits]
        for hit in hits:
            info = hit.get("info", {})
            venue = detect_venue(str(info.get("venue", "")), venues)
            year = _safe_int(info.get("year"))
            if venue != requested_venue.upper() or year < cutoff:
                continue
            authors = info.get("authors", {}).get("author", [])
            if isinstance(authors, (str, dict)):
                authors = [authors]
            author_names = [
                str(author.get("text", "")) if isinstance(author, dict) else str(author)
                for author in authors
            ]
            ee = info.get("ee", "")
            if isinstance(ee, list):
                ee = next((url for url in ee if isinstance(url, str)), "")
            doi = clean_doi(str(ee)) if "doi.org/" in str(ee) else ""
            papers.append(
                PaperCandidate(
                    title=_strip_html(str(info.get("title", ""))),
                    authors=author_names,
                    venue=venue,
                    published_at=f"{year}-01-01",
                    doi=doi,
                    entry_url=str(ee or info.get("url", "")),
                    source="dblp",
                )
            )
    return papers


def fetch_crossref(
    client: httpx.Client, venues: tuple[str, ...], contact_email: str
) -> list[PaperCandidate]:
    papers: list[PaperCandidate] = []
    cutoff = date.today().year - 10
    for requested_venue in venues:
        query = VENUE_NAMES.get(requested_venue.upper(), requested_venue)
        params = {
            "query.container-title": query,
            "filter": f"from-pub-date:{cutoff}-01-01,type:proceedings-article",
            "rows": 100,
            "select": "DOI,title,author,published,container-title,URL,abstract",
        }
        if contact_email:
            params["mailto"] = contact_email
        response = client.get(CROSSREF_API, params=params)
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
        for item in items:
            containers = item.get("container-title") or []
            venue_text = " ".join(containers)
            venue = detect_venue(venue_text, venues)
            if venue != requested_venue.upper():
                continue
            title_values = item.get("title") or []
            title = title_values[0] if title_values else ""
            if not title:
                continue
            published = item.get("published", {}).get("date-parts", [[]])
            parts = published[0] if published else []
            published_at = "-".join(
                str(value).zfill(2) if index else str(value)
                for index, value in enumerate(parts)
            )
            authors = [
                " ".join(filter(None, [author.get("given", ""), author.get("family", "")]))
                for author in item.get("author", [])
            ]
            papers.append(
                PaperCandidate(
                    title=_strip_html(title),
                    authors=authors,
                    venue=venue,
                    published_at=published_at,
                    abstract=_strip_html(item.get("abstract", "")),
                    doi=clean_doi(item.get("DOI", "")),
                    entry_url=item.get("URL", ""),
                    source="crossref",
                )
            )
    return papers


def fetch_ieee(
    client: httpx.Client, venues: tuple[str, ...], api_key: str
) -> list[PaperCandidate]:
    if not api_key:
        return []
    papers: list[PaperCandidate] = []
    cutoff = date.today().year - 10
    for requested_venue in venues:
        response = client.get(
            IEEE_API,
            params={
                "apikey": api_key,
                "publication_title": VENUE_NAMES.get(requested_venue, requested_venue),
                "start_year": cutoff,
                "max_records": 200,
                "sort_order": "desc",
                "sort_field": "publication_year",
            },
        )
        response.raise_for_status()
        for item in response.json().get("articles", []):
            venue = detect_venue(item.get("publication_title", ""), venues)
            if venue != requested_venue.upper():
                continue
            authors = [
                author.get("full_name", "")
                for author in item.get("authors", {}).get("authors", [])
            ]
            papers.append(
                PaperCandidate(
                    title=_strip_html(item.get("title", "")),
                    authors=authors,
                    venue=venue,
                    published_at=str(item.get("publication_year", "")),
                    abstract=_strip_html(item.get("abstract", "")),
                    doi=clean_doi(item.get("doi", "")),
                    entry_url=item.get("html_url") or item.get("abstract_url") or "",
                    pdf_url=item.get("pdf_url", ""),
                    source="ieee",
                )
            )
    return papers


def discover_all(
    client: httpx.Client,
    venues: tuple[str, ...],
    contact_email: str,
    ieee_api_key: str,
    preferred_keywords: tuple[str, ...] = (),
) -> Iterable[tuple[str, list[PaperCandidate] | Exception]]:
    sources = (
        ("arxiv", lambda: fetch_arxiv_preferred(client, venues, preferred_keywords)),
        ("dblp", lambda: fetch_dblp(client, venues)),
        ("crossref", lambda: fetch_crossref(client, venues, contact_email)),
        ("ieee", lambda: fetch_ieee(client, venues, ieee_api_key)),
    )
    for name, fetch in sources:
        try:
            yield name, fetch()
        except Exception as exc:
            LOG.warning("Source %s failed: %s", name, exc)
            yield name, exc


def _xml_text(element: ET.Element, path: str, ns: dict[str, str]) -> str:
    child = element.find(path, ns)
    return (child.text or "").strip() if child is not None else ""


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _strip_html(value: str) -> str:
    return _collapse(re.sub(r"<[^>]+>", " ", value))


def _safe_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0

