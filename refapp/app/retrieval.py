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


def retrieve(session: Session, query: str, k: int) -> list[RetrievedChunk]:
    """Return the top-k most similar chunks for a query.

    pgvector's `<=>` operator (exposed as .cosine_distance) returns cosine
    distance in [0, 2]; we convert to similarity = 1 - distance for display.
    """
    qvec = embed_query(query)
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
