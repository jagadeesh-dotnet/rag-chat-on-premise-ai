import pytest

from app.ingest.chunker import chunk_sections, split_text
from app.ingest.models import Section

# A long text with words, sentences and paragraphs, reused by several tests.
TEXT = "\n\n".join(
    " ".join(f"Sentence {p}.{s} has a few ordinary words in it." for s in range(8)) for p in range(12)
)


def test_empty_text_gives_no_chunks():
    assert split_text("   \n ", size=100, overlap=20) == []


def test_short_text_is_one_unchanged_chunk():
    assert split_text("  Just one short paragraph.  ", size=100, overlap=20) == ["Just one short paragraph."]


def test_chunks_never_exceed_size():
    chunks = split_text(TEXT, size=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_neighbouring_chunks_overlap():
    chunks = split_text(TEXT, size=300, overlap=50)
    for first, second in zip(chunks, chunks[1:]):
        tail = first[-20:]
        assert tail in second, f"no overlap between {first[-40:]!r} and {second[:40]!r}"


def test_no_word_is_cut_in_half():
    words = set(TEXT.split())
    for chunk in split_text(TEXT, size=300, overlap=50):
        for word in chunk.split():
            assert word in words, f"broken word {word!r}"


def test_prefers_paragraph_boundary():
    text = "A" * 70 + "\n\n" + "B" * 70
    assert split_text(text, size=100, overlap=10)[0] == "A" * 70


def test_long_word_is_split_without_endless_loop():
    chunks = split_text("x" * 3000, size=1200, overlap=200)
    assert 3 <= len(chunks) <= 4
    assert all(len(c) <= 1200 for c in chunks)


@pytest.mark.parametrize("overlap", [-1, 50, 60, 100])
def test_bad_overlap_is_rejected(overlap):
    with pytest.raises(ValueError):
        split_text("abc", size=100, overlap=overlap)


def test_chunk_sections_keeps_page_heading_and_numbers_chunks():
    sections = [
        Section(text=TEXT, page=1, heading="Intro"),
        Section(text="Second page text.", page=2, heading="Next"),
    ]
    chunks = chunk_sections("folder/file.pdf", sections, size=300, overlap=50)

    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].text == "Second page text."
    assert chunks[-1].page == 2 and chunks[-1].heading == "Next"
    assert all(c.page == 1 and c.heading == "Intro" for c in chunks[:-1])
    assert chunks[0].id == "folder/file.pdf#0"