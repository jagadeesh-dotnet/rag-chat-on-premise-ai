import hashlib
import logging
import threading
import time
from pathlib import Path

from app.config import settings
from app.ingest.chunker import chunk_sections
from app.ingest.loaders import DOCUMENT_TYPES, load_file
from app.ingest.store import get_store

log = logging.getLogger(__name__)
_lock = threading.Lock()


class IndexBusyError(RuntimeError):
    """Raised when an index run is already in progress."""


def find_documents(root: Path) -> list[Path]:
    """Supported documents under root, skipping Word lock files (~$name.docx) and hidden files."""
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in DOCUMENT_TYPES and not p.name.startswith(("~$", "."))
    )


def file_hash(path: Path) -> str:
    """SHA-256 of the file's bytes: changes whenever the content changes."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):  # 1 MB at a time: big files don't fill memory
            digest.update(block)
    return digest.hexdigest()


def index_documents(force: bool = False) -> dict:
    """Bring the index in line with docs_dir: add new files, re-index changed ones, drop removed ones."""
    if not _lock.acquire(blocking=False):
        raise IndexBusyError("indexing is already running")
    try:
        return _index(force)
    finally:
        _lock.release()


def _index(force: bool) -> dict:
    started = time.perf_counter()
    store = get_store()
    docs_dir = settings.docs_dir

    on_disk = {p.relative_to(docs_dir).as_posix(): p for p in find_documents(docs_dir)}
    indexed = store.file_hashes()  # {source: hash} from Qdrant
    summary: dict = {"added": [], "updated": [], "removed": [], "unchanged": [], "errors": {}, "chunks": 0}

    for source in sorted(indexed.keys() - on_disk.keys()):  # in the index, but the file is gone
        store.delete_source(source)
        summary["removed"].append(source)

    for source, path in on_disk.items():
        digest = file_hash(path)
        if not force and indexed.get(source) == digest:
            summary["unchanged"].append(source)
            continue
        try:
            sections = load_file(path, settings.cache_dir)
            chunks = chunk_sections(source, sections, settings.chunk_size, settings.chunk_overlap)
            store.delete_source(source)  # old chunks out first: the new version may have fewer
            summary["chunks"] += store.add(chunks, digest)
        except Exception as exc:
            log.exception("Indexing %s failed", source)
            summary["errors"][source] = str(exc)
            continue
        summary["updated" if source in indexed else "added"].append(source)

    summary["seconds"] = round(time.perf_counter() - started, 1)
    log.info("Index run: %s", {k: len(v) if isinstance(v, (list, dict)) else v for k, v in summary.items()})
    return summary
