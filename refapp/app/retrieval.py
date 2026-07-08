"""Vector retrieval over the corpus using pgvector cosine distance."""
from dataclasses import dataclass

from sqlmodel import Session, select

from app.embeddings import embed_query
from app.models import Chunk, Document


@dataclass
class RetrievedChunk:
    rank: int
    content: str
    source: str
    title: str
    score: float  # cosine similarity in [-1, 1]; higher is more similar


def retrieve_with_vector(session: Session, qvec: list[float], k: int) -> list[RetrievedChunk]:
    """Top-k retrieval using a precomputed query embedding.

    Splitting this out lets the caller embed the query once and reuse the
    vector for both retrieval and the gateway's semantic cache key.
    """
    distance = Chunk.embedding.cosine_distance(qvec)  # type: ignore[attr-defined]

    stmt = (
        select(Chunk, Document, distance.label("distance"))
        .join(Document, Document.id == Chunk.document_id)
        .order_by(distance)
        .limit(k)
    )
    rows = session.exec(stmt).all()

    results: list[RetrievedChunk] = []
    for rank, (chunk, document, dist) in enumerate(rows, start=1):
        results.append(
            RetrievedChunk(
                rank=rank,
                content=chunk.content,
                source=document.source,
                title=document.title,
                score=round(1.0 - float(dist), 4),
            )
        )
    return results


def retrieve(session: Session, query: str, k: int) -> list[RetrievedChunk]:
    """Embed the query and return the top-k most similar chunks."""
    return retrieve_with_vector(session, embed_query(query), k)
