import re
import unicodedata
from collections import Counter

_KEEP = {"\n", "\t"}
_SPACES = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_DIGITS = re.compile(r"\d+")


def clean_text(text: str) -> str:
    """Normalise characters and whitespace without changing the meaning."""
    text = unicodedata.normalize("NFKC", text)  # "ﬁ" -> "fi", no-break space -> space
    text = "".join(
        ch for ch in text
        if ch in _KEEP or unicodedata.category(ch) not in ("Cc", "Cf")  # control / invisible chars
    )
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # "infor-\nmation" -> "information"
    lines = [_SPACES.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_LINES.sub("\n\n", text)  # at most one empty line in a row
    return text.strip()


def _signature(line: str) -> str:
    """Compare lines ignoring numbers and case: 'Page 3 of 40' == 'Page 17 of 40'."""
    return _DIGITS.sub("#", line).strip().lower()


def remove_repeated_lines(pages: list[str], edge: int = 3, min_share: float = 0.5) -> list[str]:
    """Drop header/footer lines that appear at the top or bottom of most pages.

    Only the first and last `edge` lines of each page are considered, so a phrase that is
    repeated in the body text is never removed.
    """
    if len(pages) < 3:
        return pages  # too few pages to tell a header from content

    counts: Counter[str] = Counter()
    for page in pages:
        lines = [ln for ln in page.split("\n") if ln.strip()]
        edges = {_signature(ln) for ln in lines[:edge] + lines[-edge:]}
        counts.update(edges)  # a set: each signature counts once per page

    threshold = max(3, int(len(pages) * min_share))
    repeated = {sig for sig, n in counts.items() if n >= threshold and sig}

    cleaned = []
    for page in pages:
        lines = page.split("\n")
        non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_rows = set(non_empty[:edge] + non_empty[-edge:])
        kept = [
            ln for i, ln in enumerate(lines)
            if not (i in edge_rows and _signature(ln) in repeated)
        ]
        cleaned.append("\n".join(kept))
    return cleaned