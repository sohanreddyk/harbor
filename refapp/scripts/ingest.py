"""Ingest the starter corpus into Postgres + pgvector.

Usage (from repo root):
    make ingest
or:
    docker compose run --rm refapp python scripts/ingest.py

Idempotent: re-ingesting a file replaces its previous document + chunks.
"""
import sys
from pathlib import Path

from sqlmodel import Session, delete, select, text

# Allow running as `python scripts/ingest.py` from the refapp dir.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine, init_db          # noqa: E402
from app.embeddings import embed_passages    # noqa: E402
from app.models import Chunk, Document        # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parents[1] / "data" / "corpus"
MAX_CHARS = 900  # target chunk size; keeps paragraphs intact


def chunk_markdown(raw: str) -> list[str]:
    """Paragraph-aware chunking: merge paragraphs up to MAX_CHARS."""
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > MAX_CHARS:
            chunks.append(buf.strip())
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def ingest_file(session: Session, path: Path) -> int:
    source = path.name
    title = path.stem.replace("-", " ").replace("_", " ").title()
    raw = path.read_text(encoding="utf-8")

    # Replace any prior version of this document.
    existing = session.exec(select(Document).where(Document.source == source)).all()
    for doc in existing:
        session.exec(delete(Chunk).where(Chunk.document_id == doc.id))
        session.delete(doc)
    session.commit()

    document = Document(source=source, title=title)
    session.add(document)
    session.commit()
    session.refresh(document)

    texts = chunk_markdown(raw)
    vectors = embed_passages(texts)
    for i, (content, vec) in enumerate(zip(texts, vectors)):
        session.add(
            Chunk(
                document_id=document.id,
                chunk_index=i,
                content=content,
                token_count=len(content.split()),
                embedding=vec,
            )
        )
    session.commit()
    return len(texts)


def ensure_hnsw_index(session: Session) -> None:
    session.exec(
        text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding "
            "ON corpus_chunks USING hnsw (embedding vector_cosine_ops)"
        )
    )
    session.commit()


def main() -> None:
    init_db()
    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        print(f"No .md files found in {CORPUS_DIR}")
        sys.exit(1)

    total = 0
    with Session(engine) as session:
        for path in files:
            n = ingest_file(session, path)
            total += n
            print(f"  ingested {path.name}: {n} chunks")
        ensure_hnsw_index(session)

    print(f"Done. {len(files)} documents, {total} chunks embedded.")


if __name__ == "__main__":
    main()
