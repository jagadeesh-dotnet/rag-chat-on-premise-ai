"""Load and chunk every document in docs_dir.

    python -m app.ingest                 all files
    python -m app.ingest --only iso      only files whose path contains "iso"
"""

import argparse
import json
import logging
import time
from pathlib import Path

from app.config import settings
from app.ingest.chunker import chunk_sections
from app.ingest.loaders import load_file
from app.ingest.models import Chunk


def find_documents(root: Path) -> list[Path]:
    """All files under root, skipping Word lock files (~$name.docx) and hidden files."""
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and not p.name.startswith(("~$", "."))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load and chunk documents")
    parser.add_argument("--only", help="process only files whose path contains this text")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    docs_dir = settings.docs_dir
    all_chunks: list[Chunk] = []

    print(f"Documents in {docs_dir}\n")
    print(f"{'file':40} {'type':5} {'parts':>5} {'chunks':>6} {'avg len':>7} {'max len':>7} {'secs':>5}")
    for path in find_documents(docs_dir):
        source = path.relative_to(docs_dir).as_posix()  # "hr/handbook.docx", always with "/"
        if args.only and args.only.lower() not in source.lower():
            continue

        started = time.perf_counter()
        try:
            sections = load_file(path, settings.cache_dir)
        except Exception as exc:  # one broken file must not stop the others
            print(f"{source:40} ERROR: {exc}")
            continue
        chunks = chunk_sections(source, sections, settings.chunk_size, settings.chunk_overlap)
        seconds = time.perf_counter() - started

        if not chunks:
            continue  # skipped type (already logged) or no text
        lengths = [len(c.text) for c in chunks]
        print(
            f"{source[:40]:40} {path.suffix[1:]:5} {len(sections):>5} {len(chunks):>6} "
            f"{sum(lengths) // len(lengths):>7} {max(lengths):>7} {seconds:>5.1f}"
        )
        all_chunks.extend(chunks)

    out = settings.cache_dir / "chunks.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")
    print(f"\n{len(all_chunks)} chunks written to {out}")


if __name__ == "__main__":
    main()