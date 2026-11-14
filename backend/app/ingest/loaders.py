import hashlib
import logging
import re
from pathlib import Path

import pymupdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.config import settings
from app.ingest.cleaning import clean_text, remove_repeated_lines
from app.ingest.models import Section
from app.ingest.ocr import ocr_available, ocr_image

log = logging.getLogger(__name__)

SPREADSHEETS = {".xlsx", ".xls", ".csv"}  # handled as SQL tables in step 7, not chunked
IMAGES = {".png", ".jpg", ".jpeg"}  # read with OCR
DOCUMENT_TYPES = {".pdf", ".docx", ".doc"} | IMAGES  # what the indexer embeds


def _page_text(page: pymupdf.Page, use_ocr: bool) -> tuple[str, bool]:
    """The page's text layer, or OCR when the page is a scan (almost no text, but an image)."""
    text = page.get_text()  # default reading order, no sort=True
    if len(text.strip()) >= settings.ocr_min_chars or not page.get_images() or not use_ocr:
        return text, False
    image = page.get_pixmap(dpi=settings.ocr_dpi).tobytes("png")
    return ocr_image(image), True


# A line that is only "Annex A" starts an annex (the table of contents line has more text, so it doesn't match).
_ANNEX_START = re.compile(r"^\s*(Annex [A-Z])\s*$", re.MULTILINE)
_ANNEX_END = re.compile(r"^\s*Bibliography\s*$", re.MULTILINE)


def load_pdf(path: Path) -> list[Section]:
    """One section per page, with repeated headers/footers removed.

    Pages inside an annex get heading "Annex A" etc., so its "6.2" isn't confused with clause 6.2.
    Scanned pages are read with OCR.
    """
    use_ocr = ocr_available()
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("the PDF is password-protected")
        pages, ocr_pages = [], []
        for number, page in enumerate(pdf, start=1):
            text, was_ocr = _page_text(page, use_ocr)
            pages.append(clean_text(text))
            if was_ocr:
                ocr_pages.append(number)
    pages = remove_repeated_lines(pages)

    if ocr_pages:
        log.info("%s: OCR on page(s) %s", path.name, ocr_pages)
    empty = [n for n, text in enumerate(pages, start=1) if not text.strip()]
    if empty:
        log.warning("%s: no text on page(s) %s - not searchable", path.name, empty)

    sections, part = [], None
    for number, text in enumerate(pages, start=1):
        if start := _ANNEX_START.search(text):
            part = start.group(1)
        elif _ANNEX_END.search(text):
            part = None
        if text.strip():
            sections.append(Section(text=text, page=number, heading=part))
    return sections


def _table_lines(table: Table) -> list[str]:
    """Each row as 'cell | cell | cell'. Merged cells repeat in python-docx, so skip repeats."""
    lines = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            value = cell.text.strip()
            if value and (not cells or cells[-1] != value):
                cells.append(value)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _is_heading(paragraph: Paragraph) -> bool:
    name = paragraph.style.name if paragraph.style is not None else ""
    return name.startswith("Heading") or name == "Title"


def load_docx(path: Path) -> list[Section]:
    """One section per heading, in document order, including tables."""
    document = Document(str(path))
    sections: list[Section] = []
    heading: str | None = None
    lines: list[str] = []

    def flush() -> None:
        text = clean_text("\n".join(lines))
        if text:
            sections.append(Section(text=text, heading=heading))

    for block in document.iter_inner_content():  # paragraphs AND tables, in the order they appear
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if _is_heading(block):
                flush()
                heading, lines = text, [text]  # keep the heading in the text too: it helps search
            else:
                lines.append(text)
        elif isinstance(block, Table):
            lines.extend(_table_lines(block))
    flush()
    return sections


def _convert_doc_to_docx(path: Path, cache_dir: Path) -> Path:
    """Save a .docx copy of a legacy .doc using Word. Reuses the copy if it's up to date."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]  # same name in two folders -> no clash
    target = cache_dir / f"{path.stem}-{key}.docx"
    if target.exists() and target.stat().st_mtime >= path.stat().st_mtime:
        return target

    import pythoncom  # Windows only: imported here so the rest of the module works anywhere
    import win32com.client

    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")  # a NEW Word, never the user's open one
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(
            str(path.resolve()), ReadOnly=True, AddToRecentFiles=False, ConfirmConversions=False
        )
        try:
            doc.SaveAs2(str(target.resolve()), FileFormat=16)  # 16 = wdFormatXMLDocument (.docx)
        finally:
            doc.Close(SaveChanges=False)
    finally:
        if word is not None:
            word.Quit()  # otherwise WINWORD.EXE keeps running in the background
        pythoncom.CoUninitialize()
    return target


def load_image(path: Path) -> list[Section]:
    """A picture of a document (photo, screenshot, scan) read with OCR."""
    if not ocr_available():
        log.warning("Skipping %s: images need OCR, which is off or not installed", path.name)
        return []
    text = clean_text(ocr_image(path.read_bytes()))
    if not text:
        log.warning("%s: OCR found no text", path.name)
        return []
    return [Section(text=text)]


def load_file(path: Path, cache_dir: Path) -> list[Section]:
    """Read any supported file. Unsupported types return [] with a log message."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return load_pdf(path)
    if suffix in IMAGES:
        return load_image(path)
    if suffix == ".docx":
        return load_docx(path)
    if suffix == ".doc":
        return load_docx(_convert_doc_to_docx(path, cache_dir / "converted"))
    if suffix in SPREADSHEETS:
        log.info("Skipping %s: spreadsheets are queried as tables (step 7)", path.name)
    else:
        log.info("Skipping %s: unsupported file type", path.name)
    return []
