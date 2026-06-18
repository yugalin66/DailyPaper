from paperbot.papers import PaperReader


def test_pdf_meta_extraction_handles_relative_url():
    html = '<meta name="citation_pdf_url" content="/paper.pdf">'
    assert PaperReader._pdf_links(html, "https://example.com/article") == [
        "https://example.com/paper.pdf"
    ]


def test_pdf_anchor_extraction():
    html = '<a href="files/paper.pdf?download=1">PDF</a>'
    assert PaperReader._pdf_links(html, "https://example.com/a/") == [
        "https://example.com/a/files/paper.pdf?download=1"
    ]

