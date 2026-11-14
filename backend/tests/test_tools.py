from app.agent import cited_numbers, strip_citations
from app.tools.documents import format_results

RESULTS = [
    {"source": "iso27001.pdf", "page": 11, "heading": None, "text": "6.2 Information security objectives"},
    {"source": "hr/handbook.docx", "page": None, "heading": "Annual leave", "text": "27 days per year."},
]


def test_format_results_numbers_from_first_number():
    text, passages = format_results(RESULTS, first_number=6)
    assert text.startswith("[6] iso27001.pdf, page 11\n6.2 Information security objectives")
    assert "[7] hr/handbook.docx - Annual leave\n27 days per year." in text
    assert [p["number"] for p in passages] == [6, 7]
    assert passages[1] == {
        "number": 7,
        "source": "hr/handbook.docx",
        "page": None,
        "heading": "Annual leave",
        "snippet": "27 days per year.",
    }


def test_format_results_without_results():
    text, passages = format_results([], first_number=1)
    assert passages == []
    assert "No relevant passages" in text


def test_cited_numbers_reads_single_grouped_and_repeated_citations():
    assert cited_numbers("27 days [1]. Carry over 5 [2, 3][3]. Not a citation: [x] or [].") == {1, 2, 3}


def test_strip_citations_removes_markers_and_the_space_before_them():
    assert strip_citations("Employees get 27 days [1]. Up to 5 carry over [2, 3].") == (
        "Employees get 27 days. Up to 5 carry over."
    )
