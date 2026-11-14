import re
import zlib
from collections import Counter

# Very common words carry no meaning for search ("the", "of"...).
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "must",
        "not",
        "of",
        "on",
        "or",
        "our",
        "shall",
        "should",
        "so",
        "such",
        "than",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)

_WORD = re.compile(r"\w+")
# Clause/control numbers: 6.2, 9.3.1, A.5.15 (an optional capital letter, then numbers joined by dots).
_IDENTIFIER = re.compile(r"\b(?:[A-Z]\.)?\d+(?:\.\d+)+\b")

# BM25 parameters: K1 = how fast repeated words stop adding weight, B = how much long chunks are penalised.
K1 = 1.2
B = 0.75
AVG_TOKENS = 150  # typical tokens per chunk (about 900 characters); good enough as a fixed value


def tokenize(text: str) -> list[str]:
    """Lowercase words without stopwords or single characters."""
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in STOPWORDS]


def term_index(term: str) -> int:
    """A stable number for a word. Python's hash() changes on every run, crc32 never does."""
    return zlib.crc32(term.encode("utf-8"))


def document_vector(text: str) -> tuple[list[int], list[float]]:
    """BM25 term weights for a stored chunk. Qdrant adds the IDF part (Modifier.IDF)."""
    tokens = tokenize(text)
    if not tokens:
        return [], []
    length_norm = 1 - B + B * len(tokens) / AVG_TOKENS
    weights: dict[int, float] = {}
    for term, tf in Counter(tokens).items():
        weights[term_index(term)] = tf * (K1 + 1) / (tf + K1 * length_norm)
    return list(weights.keys()), list(weights.values())


def query_vector(text: str) -> tuple[list[int], list[float]]:
    """Each distinct word of the question counts once."""
    indices = sorted({term_index(t) for t in tokenize(text)})
    return indices, [1.0] * len(indices)


def extract_identifiers(text: str) -> list[str]:
    """Clause and control numbers in the text, e.g. ['6.2', 'A.5.15']."""
    return sorted({m.upper() for m in _IDENTIFIER.findall(text)})


# A line that starts with an identifier followed by a capitalised word is a clause title:
# "6.2 Information security objectives", "5.15 Access control".
_TITLE_LINE = re.compile(r"^\s*((?:[A-Z]\.)?\d+(?:\.\d+)+)\s+[A-Z]", re.MULTILINE)


_ANNEX = re.compile(r"^Annex ([A-Z])\b")


def scoped_identifiers(identifiers: list[str], heading: str | None) -> list[str]:
    """Inside 'Annex A' tables write controls as '5.15'; their real name is 'A.5.15'.

    Prefixing them keeps Annex A control 6.2 apart from clause 6.2 of the main text.
    """
    annex = _ANNEX.match(heading or "")
    if not annex:
        return identifiers
    return sorted({i if i[0].isalpha() else f"{annex.group(1)}.{i}" for i in identifiers})


def title_identifiers(text: str) -> list[str]:
    """Identifiers that start a title line: the clause this chunk is *about*, not just mentions."""
    return sorted({m.upper() for m in _TITLE_LINE.findall(text)})
