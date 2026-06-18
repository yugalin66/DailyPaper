from paperbot.models import PaperCandidate
from paperbot.sources import clean_doi, detect_venue, fetch_arxiv_preferred


def test_detect_venue_acronym_and_long_name():
    venues = ("ISCA", "MICRO", "HPCA", "ASPLOS")
    assert detect_venue("Proceedings of the 52nd ISCA", venues) == "ISCA"
    assert detect_venue(
        "IEEE International Symposium on High Performance Computer Architecture", venues
    ) == "HPCA"


def test_detect_venue_does_not_match_word_fragment():
    assert detect_venue("A microscopic cache study", ("MICRO",)) == ""


def test_clean_doi():
    assert clean_doi("https://doi.org/10.1145/123.456") == "10.1145/123.456"


def test_preferred_arxiv_query_falls_back_to_general(monkeypatch):
    calls = []
    general = PaperCandidate(
        title="General Paper", entry_url="https://arxiv.org/abs/1", source="arxiv"
    )

    def fake_fetch(client, venues, max_results=100, query="cat:cs.AR"):
        calls.append(query)
        if "GPU" in query:
            raise RuntimeError("rate limited")
        return [general]

    monkeypatch.setattr("paperbot.sources.fetch_arxiv", fake_fetch)
    monkeypatch.setattr("paperbot.sources.time.sleep", lambda _: None)
    result = fetch_arxiv_preferred(None, ("ISCA",), ("GPU", "GPGPU"))
    assert result == [general]
    assert len(calls) == 2


def test_preferred_arxiv_results_survive_general_failure(monkeypatch):
    preferred = PaperCandidate(
        title="GPU Paper", entry_url="https://arxiv.org/abs/2", source="arxiv"
    )

    def fake_fetch(client, venues, max_results=100, query="cat:cs.AR"):
        if "GPU" in query:
            return [preferred]
        raise RuntimeError("rate limited")

    monkeypatch.setattr("paperbot.sources.fetch_arxiv", fake_fetch)
    monkeypatch.setattr("paperbot.sources.time.sleep", lambda _: None)
    assert fetch_arxiv_preferred(None, ("ISCA",), ("GPU",)) == [preferred]
