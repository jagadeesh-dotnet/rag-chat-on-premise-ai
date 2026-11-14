import importlib.util

import pymupdf
import pytest

from app.ingest import loaders
from app.ingest.ocr import boxes_to_text

HAS_RAPIDOCR = importlib.util.find_spec("rapidocr_onnxruntime") is not None
needs_rapidocr = pytest.mark.skipif(not HAS_RAPIDOCR, reason="rapidocr-onnxruntime not installed")

TEXT = "Employees receive 27 days of annual leave per year.\nUnused leave can be carried over."


def box(x, y, text, confidence=0.9, w=100, h=20):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], text, confidence


def test_boxes_are_put_in_reading_order():
    boxes = [box(200, 0, "world"), box(0, 2, "Hello"), box(0, 30, "second line")]
    assert boxes_to_text(boxes, min_confidence=0.5) == "Hello world\nsecond line"


def test_big_vertical_gap_starts_a_paragraph():
    boxes = [box(0, 0, "Title"), box(0, 100, "Body text")]
    assert boxes_to_text(boxes, min_confidence=0.5) == "Title\n\nBody text"


def test_unsure_text_is_dropped():
    assert boxes_to_text([box(0, 0, "noise", confidence=0.2)], min_confidence=0.5) == ""


def _text_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), TEXT, fontsize=16)
    doc.save(path)
    return path


def _scanned_pdf(path, tmp_path):
    """A PDF whose only page is a picture of text, like a scanner makes."""
    text_doc = pymupdf.open(_text_pdf(tmp_path / "source.pdf"))
    picture = text_doc[0].get_pixmap(dpi=150)
    scan = pymupdf.open()
    page = scan.new_page()
    page.insert_image(page.rect, pixmap=picture)
    scan.save(path)
    return path


def test_pages_with_a_text_layer_are_not_ocrd(tmp_path, monkeypatch):
    def fail(_image):
        raise AssertionError("OCR must not run on a page that has text")

    monkeypatch.setattr(loaders, "ocr_image", fail)
    monkeypatch.setattr(loaders, "ocr_available", lambda: True)
    sections = loaders.load_pdf(_text_pdf(tmp_path / "text.pdf"))
    assert "annual leave" in sections[0].text


@needs_rapidocr
def test_scanned_pdf_page_is_read_with_ocr(tmp_path):
    sections = loaders.load_pdf(_scanned_pdf(tmp_path / "scan.pdf", tmp_path))
    text = sections[0].text.lower()
    assert "annual leave" in text and "27 days" in text


@needs_rapidocr
def test_image_file_is_read_with_ocr(tmp_path):
    image = tmp_path / "photo.png"
    pymupdf.open(_text_pdf(tmp_path / "source.pdf"))[0].get_pixmap(dpi=150).save(image)
    sections = loaders.load_file(image, tmp_path)
    assert "carried over" in sections[0].text.lower()
