from collections.abc import Iterable

from ollama import Client

from app.config import settings
from app.ingest.models import Chunk

# nomic-embed-text was trained with these task prefixes: documents and questions get different ones.
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

_client = Client(host=settings.ollama_host)


def chunk_text_for_embedding(chunk: Chunk) -> str:
    """The text that represents a chunk: its heading (if not already there) plus its text."""
    if chunk.heading and not chunk.text.startswith(chunk.heading):
        return f"{chunk.heading}\n{chunk.text}"
    return chunk.text


def _batches(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def embed_documents(texts: list[str]) -> list[list[float]]:
    """One vector per text, in the same order. Sent to Ollama in batches."""
    vectors: list[list[float]] = []
    for batch in _batches(texts, settings.embed_batch):
        response = _client.embed(
            model=settings.embed_model,
            input=[DOCUMENT_PREFIX + text for text in batch],
        )
        vectors.extend(response.embeddings)
    if len(vectors) != len(texts):
        raise RuntimeError(f"expected {len(texts)} embeddings, got {len(vectors)}")
    return vectors


def embed_query(text: str) -> list[float]:
    """The vector for a user's question."""
    response = _client.embed(model=settings.embed_model, input=QUERY_PREFIX + text)
    return response.embeddings[0]
