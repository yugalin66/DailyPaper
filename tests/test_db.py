from pathlib import Path

from paperbot.db import Database
from paperbot.models import PaperCandidate, PaperSummary


def make_paper(**overrides):
    values = {
        "title": "The Same Paper",
        "authors": ["A. Author"],
        "venue": "ISCA",
        "published_at": "2026-01-01",
        "entry_url": "https://example.com/paper",
        "source": "test",
    }
    values.update(overrides)
    return PaperCandidate(**values)


def make_summary():
    return PaperSummary(
        title="The Same Paper",
        paper_url="https://example.com/paper",
        authors=["A. Author"],
        venue="ISCA",
        overview=["overview"],
        problem=["problem"],
        solution_architecture=["solution"],
        results=["result"],
        comparisons=["comparison"],
        future_work_explicit=["none"],
        future_work_inferred=["推論：extension"],
    )


def test_upsert_deduplicates_by_normalized_title(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite3")
    first = db.upsert(make_paper())
    second = db.upsert(make_paper(doi="10.1000/example"))
    assert first == second
    db.close()


def test_pending_summary_and_mark_sent(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite3")
    paper_id = db.upsert(make_paper())
    db.save_summary(paper_id, make_summary(), "gemini-test")
    pending = db.pending_summary()
    assert pending is not None
    assert pending[2] == "gemini-test"
    db.mark_sent(paper_id)
    assert db.pending_summary() is None
    db.close()


def test_candidates_prioritize_gpu_top_venue(tmp_path: Path):
    db = Database(tmp_path / "ranking.sqlite3")
    db.upsert(make_paper(title="New CPU Paper", published_at="2026-06-01"))
    db.upsert(make_paper(title="Older GPU Paper", published_at="2025-06-01"))
    db.upsert(make_paper(
        title="Newest GPGPU arXiv Paper", venue="", published_at="2026-06-10"
    ))
    candidates = db.candidates(("ISCA",), ("GPU", "GPGPU"), 10)
    assert [paper.title for paper in candidates] == [
        "Older GPU Paper",
        "New CPU Paper",
        "Newest GPGPU arXiv Paper",
    ]
    db.close()
