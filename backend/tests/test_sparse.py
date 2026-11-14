from app.ingest.sparse import (
    document_vector,
    extract_identifiers,
    query_vector,
    scoped_identifiers,
    term_index,
    title_identifiers,
    tokenize,
)


def test_tokenize_drops_stopwords_and_single_characters():
    assert tokenize("The annual leave of a year, in 6.2") == ["annual", "leave", "year"]


def test_term_index_is_stable():
    # Golden value: if hashing ever changes, every stored BM25 vector silently stops matching.
    assert term_index("leave") == 2612035792


def test_repeated_word_weighs_more_but_not_linearly():
    _, once = document_vector("leave")
    _, three = document_vector("leave leave leave")
    assert once[0] < three[0] < 3 * once[0]


def test_same_word_weighs_less_in_a_longer_chunk():
    _, short = document_vector("leave policy")
    long_idx, long_vals = document_vector("leave " + " ".join(f"filler{i}" for i in range(300)))
    assert long_vals[long_idx.index(term_index("leave"))] < short[0]


def test_query_vector_counts_each_word_once():
    indices, values = query_vector("leave leave policy")
    assert len(indices) == 2 and values == [1.0, 1.0]


def test_extract_identifiers():
    assert extract_identifiers("See clause 6.2 and control A.5.15, not page 6") == ["6.2", "A.5.15"]


def test_scoped_identifiers_prefixes_numbers_inside_an_annex():
    assert scoped_identifiers(["5.15", "6.2", "A.8.1"], "Annex A") == ["A.5.15", "A.6.2", "A.8.1"]


def test_scoped_identifiers_leaves_main_text_alone():
    assert scoped_identifiers(["6.2"], None) == ["6.2"]
    assert scoped_identifiers(["6.2"], "Annual leave") == ["6.2"]


def test_title_identifiers_only_counts_lines_that_start_a_clause():
    text = "see 6.2 for details\n5.15 Access control\nControl rules"
    assert title_identifiers(text) == ["5.15"]
