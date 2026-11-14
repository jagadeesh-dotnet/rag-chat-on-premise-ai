from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Section:
    """A block of text read from a file, before chunking (a PDF page or a Word section)."""

    text: str
    page: int | None = None
    heading: str | None = None


@dataclass(frozen=True)
class Chunk:
    """A piece of a document, small enough to embed and search."""

    source: str  # path relative to docs_dir, always with "/": "hr/hr-handbook-sample.docx"
    index: int  # position within the file: 0, 1, 2...
    text: str
    page: int | None = None  # PDF page number (1-based), None for Word files
    heading: str | None = None  # nearest heading above this text, if known

    @property
    def id(self) -> str:
        """Stable ID, e.g. 'iso27001.pdf#12'. The same file always gives the same IDs."""
        return f"{self.source}#{self.index}"

    def to_dict(self) -> dict:
        return {"id": self.id, **asdict(self)}