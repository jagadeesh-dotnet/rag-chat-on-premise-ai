import threading
import uuid
from collections import Counter
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.config import settings
from app.ingest.embeddings import chunk_text_for_embedding, embed_documents, embed_query
from app.ingest.models import Chunk
from app.ingest.sparse import (
    document_vector,
    extract_identifiers,
    query_vector,
    scoped_identifiers,
    title_identifiers,
)

DENSE = "dense"
SPARSE = "bm25"
CANDIDATES = 20  # results taken from each search before fusing
RRF_K = 60  # standard RRF constant: dampens the gap between rank 1 and rank 2
WEIGHTS = {"dense": 1.0, "sparse": 1.0, "ident": 3.0}  # an exact clause number is a strong signal


def point_id(chunk_id: str) -> str:
    """Qdrant IDs must be ints or UUIDs. uuid5 gives the same UUID for the same chunk every time."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def _match(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _filter(source: str | None = None, idents: list[str] | None = None) -> models.Filter | None:
    must: list[models.Condition] = []
    if source:
        must.append(_match("source", source))
    if idents:
        must.append(models.FieldCondition(key="idents", match=models.MatchAny(any=idents)))
    return models.Filter(must=must) if must else None


class DocumentStore:
    def __init__(self, path: str, collection: str) -> None:
        self._client = QdrantClient(path=path)  # local mode: a folder, no server
        self._collection = collection
        self._lock = threading.Lock()  # FastAPI runs `def` endpoints on several threads

    # --- writing ------------------------------------------------------------------------------

    def _ensure_collection(self, vector_size: int) -> None:
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                self._collection,
                vectors_config={
                    DENSE: models.VectorParams(size=vector_size, distance=models.Distance.COSINE)
                },
                # IDF modifier: Qdrant weighs rare words higher, using statistics of the whole collection.
                sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )

    def add(self, chunks: list[Chunk], file_hash: str) -> int:
        """Embed and store chunks (all from one file). Returns how many were stored."""
        if not chunks:
            return 0
        texts = [chunk_text_for_embedding(c) for c in chunks]
        vectors = embed_documents(texts)  # slow part: outside the lock
        points = []
        for chunk, text, vector in zip(chunks, texts, vectors):
            indices, values = document_vector(text)
            points.append(
                models.PointStruct(
                    id=point_id(chunk.id),
                    vector={DENSE: vector, SPARSE: models.SparseVector(indices=indices, values=values)},
                    payload={
                        **chunk.to_dict(),
                        "file_hash": file_hash,
                        "idents": scoped_identifiers(extract_identifiers(text), chunk.heading),
                        "title_idents": scoped_identifiers(title_identifiers(text), chunk.heading),
                    },
                )
            )
        with self._lock:
            self._ensure_collection(len(vectors[0]))
            self._client.upsert(self._collection, points=points)
        return len(points)

    def delete_source(self, source: str) -> None:
        """Remove every chunk of one file."""
        with self._lock:
            if self._client.collection_exists(self._collection):
                self._client.delete(
                    self._collection, points_selector=models.FilterSelector(filter=_filter(source=source))
                )

    # --- reading ------------------------------------------------------------------------------

    def _all_payloads(self, fields: list[str]) -> list[dict]:
        """Page through every point, reading only the given payload fields."""
        if not self._client.collection_exists(self._collection):
            return []
        payloads, offset = [], None
        while True:
            points, offset = self._client.scroll(
                self._collection, limit=256, offset=offset, with_payload=fields, with_vectors=False
            )
            payloads.extend(p.payload or {} for p in points)
            if offset is None:
                return payloads

    def file_hashes(self) -> dict[str, str]:
        """{source: file_hash} for every indexed file (used to skip unchanged files)."""
        with self._lock:
            return {p["source"]: p["file_hash"] for p in self._all_payloads(["source", "file_hash"])}

    def chunk_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(Counter(p["source"] for p in self._all_payloads(["source"])))

    def _query(self, query, using: str, flt: models.Filter | None, limit: int = CANDIDATES):
        return self._client.query_points(
            self._collection, query=query, using=using, query_filter=flt, limit=limit, with_payload=True
        ).points

    def search(
        self, query: str, k: int, source: str | None = None, min_score: float | None = None
    ) -> list[dict]:
        """Hybrid search: meaning (dense) + exact words (BM25) + clause numbers, fused with RRF."""
        min_score = settings.min_score if min_score is None else min_score
        dense_vector = embed_query(query)  # outside the lock: it calls Ollama
        indices, values = query_vector(query)
        wanted = extract_identifiers(query)  # "clause 6.2" -> 6.2 (main text), "A.5.15" -> Annex A only

        with self._lock:
            if not self._client.collection_exists(self._collection):
                return []
            rankings = {"dense": self._query(dense_vector, DENSE, _filter(source))}
            if indices:
                sparse = models.SparseVector(indices=indices, values=values)
                rankings["sparse"] = self._query(sparse, SPARSE, _filter(source))
            if wanted:  # only chunks containing the clause number, ordered by meaning
                rankings["ident"] = self._query(dense_vector, DENSE, _filter(source, wanted))

            # Reciprocal Rank Fusion: each list adds weight / (60 + rank). Only ranks matter, not scores.
            fused: dict[str, float] = {}
            payloads: dict[str, dict] = {}
            similarity: dict[str, float] = {}  # cosine from the dense searches, for the min_score cutoff
            for name, points in rankings.items():
                for rank, p in enumerate(points, start=1):
                    fused[p.id] = fused.get(p.id, 0.0) + WEIGHTS[name] / (RRF_K + rank)
                    payloads[p.id] = p.payload or {}
                    if name != "sparse":
                        similarity[p.id] = p.score

            # Chunks found only by BM25 have no cosine yet: ask Qdrant for exactly those.
            missing = [pid for pid in fused if pid not in similarity]
            if missing:
                only = models.Filter(must=[models.HasIdCondition(has_id=missing)])
                for p in self._query(dense_vector, DENSE, only, limit=len(missing)):
                    similarity[p.id] = p.score

        results = []
        for pid in sorted(fused, key=fused.get, reverse=True):
            payload = payloads[pid]
            is_the_clause = bool(set(wanted) & set(payload.get("title_idents", [])))
            if similarity.get(pid, 0.0) < min_score and not is_the_clause:
                continue  # too far in meaning, and not the clause that was asked for
            results.append(
                {
                    "source": payload["source"],
                    "page": payload.get("page"),
                    "heading": payload.get("heading"),
                    "text": payload["text"],
                    "score": round(fused[pid], 4),
                    "similarity": round(similarity.get(pid, 0.0), 4),
                }
            )
            if len(results) == k:
                break
        return results

    def close(self) -> None:
        with self._lock:
            self._client.close()


@lru_cache
def get_store() -> DocumentStore:
    """One store for the whole process (local mode allows only one client per folder)."""
    return DocumentStore(str(settings.qdrant_path), settings.qdrant_collection)
