from app.ingest.models import Chunk, Section

# Best place to cut first: paragraph, line, sentence, clause, word.
_SEPARATORS = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


def _best_cut(text: str, start: int, end: int) -> int:
    """Position to cut text[start:end], preferring the strongest boundary in its second half."""
    min_cut = start + (end - start) // 2  # never make a chunk less than half the size
    for sep in _SEPARATORS:
        pos = text.rfind(sep, min_cut, end)
        if pos != -1:
            return pos + len(sep)  # keep the separator with the chunk that ends there
    return end  # no boundary at all (e.g. one very long "word"): hard cut


def split_text(text: str, size: int, overlap: int) -> list[str]:
    """Split text into pieces of at most `size` characters; neighbours share about `overlap`."""
    if not 0 <= overlap < size // 2:
        raise ValueError("overlap must be at least 0 and less than half of size")

    text = text.strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        cut = end if end == len(text) else _best_cut(text, start, end)

        piece = text[start:cut].strip()
        if piece:
            chunks.append(piece)
        if cut >= len(text):
            break

        # Next chunk starts `overlap` characters back, moved forward to the start of a word.
        back = cut - overlap
        space = text.find(" ", back, cut)
        next_start = space + 1 if space != -1 else back
        start = max(next_start, start + 1)  # always move forward: no infinite loop
    return chunks


def chunk_sections(source: str, sections: list[Section], size: int, overlap: int) -> list[Chunk]:
    """Chunk each section separately, so every chunk keeps an exact page and heading."""
    chunks: list[Chunk] = []
    for section in sections:
        for piece in split_text(section.text, size, overlap):
            chunks.append(
                Chunk(
                    source=source,
                    index=len(chunks),
                    text=piece,
                    page=section.page,
                    heading=section.heading,
                )
            )
    return chunks