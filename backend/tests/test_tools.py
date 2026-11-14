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