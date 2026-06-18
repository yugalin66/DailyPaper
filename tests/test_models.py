from paperbot.models import PaperCandidate, matches_keywords, normalize_title


def test_normalize_title_ignores_punctuation_and_case():
    assert normalize_title("A Fast, New CPU!") == "a fast new cpu"


def test_candidate_key_deduplicates_sources_by_title():
    doi_paper = PaperCandidate(
        title="An Example Paper", doi="10.1000/ABC",
        entry_url="https://example.com", source="crossref",
    )
    arxiv_paper = PaperCandidate(
        title="An example paper!", arxiv_id="2401.00001v2",
        entry_url="https://arxiv.org/abs/2401.00001", source="arxiv",
    )
    assert doi_paper.canonical_key == arxiv_paper.canonical_key


def test_different_titles_have_different_keys():
    common = {"entry_url": "https://example.com", "source": "test"}
    first = PaperCandidate(title="First paper", **common)
    second = PaperCandidate(title="Second paper", **common)


def test_keyword_matching_uses_title_and_abstract_words():
    title_match = PaperCandidate(
        title="Efficient GPGPU Scheduling", entry_url="https://example.com/1", source="test"
    )
    abstract_match = PaperCandidate(
        title="Accelerator Scheduling", abstract="Evaluated on modern GPUs.",
        entry_url="https://example.com/2", source="test"
    )
    false_match = PaperCandidate(
        title="A GPUpdate Algorithm", entry_url="https://example.com/3", source="test"
    )
    assert matches_keywords(title_match, ("GPU", "GPGPU"))
    assert matches_keywords(abstract_match, ("GPU", "GPGPU"))
    assert not matches_keywords(false_match, ("GPU", "GPGPU"))
