"""OCR for scanned pages and images, with RapidOCR (models ship inside the pip package, runs offline).

Everything OCR-specific lives here behind ocr_image(), so the engine can be swapped later.
"""

import logging
from functools import lru_cache

from app.config import settings

log = logging.getLogger(__name__)

# One recognised piece of text: (box corners [[x, y] x4], text, confidence).
Box = tuple[list[list[float]], str, float]


@lru_cache
def _engine():
    """Load the models once (takes a second or two), on first use only."""
    # Imported here, not at the top: the app still starts if OCR isn't installed.
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def ocr_available() -> bool:
    if not settings.ocr_enabled:
        return False
    try:
        _engine()
        return True
    except ImportError:
        log.warning("OCR is enabled but rapidocr-onnxruntime isn't installed: scanned pages are skipped")
        return False


def boxes_to_text(boxes: list[Box], min_confidence: float) -> str:
    """Put recognised boxes back in reading order: lines top to bottom, words left to right.

    Boxes whose vertical centres are close belong to the same line. A big vertical gap starts a new
    paragraph (an empty line), which the chunker uses as its preferred cut.
    """
    items = []
    for corners, text, confidence in boxes:
        if confidence < min_confidence or not text.strip():
            continue
        ys = [y for _, y in corners]
        xs = [x for x, _ in corners]
        items.append({"top": min(ys), "bottom": max(ys), "left": min(xs), "text": text.strip()})
    if not items:
        return ""

    items.sort(key=lambda b: (b["top"], b["left"]))
    lines: list[list[dict]] = []
    for item in items:
        centre = (item["top"] + item["bottom"]) / 2
        if lines:
            last = lines[-1]
            top, bottom = min(b["top"] for b in last), max(b["bottom"] for b in last)
            if top <= centre <= bottom:  # overlaps the current line vertically: same line
                last.append(item)
                continue
        lines.append([item])

    out: list[str] = []
    previous_bottom, previous_height = None, None
    for line in lines:
        line.sort(key=lambda b: b["left"])
        top, bottom = min(b["top"] for b in line), max(b["bottom"] for b in line)
        height = bottom - top
        if previous_bottom is not None and top - previous_bottom > 1.0 * max(height, previous_height):
            out.append("")  # large gap: new paragraph
        out.append(" ".join(b["text"] for b in line))
        previous_bottom, previous_height = bottom, height
    return "\n".join(out)


def ocr_image(image: bytes) -> str:
    """Text in an image (PNG/JPEG bytes), in reading order."""
    result, _ = _engine()(image)
    return boxes_to_text(result or [], settings.ocr_min_confidence)
