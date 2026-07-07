"""Database models for the reference corpus.

Week 1 only needs the retrieval tables (documents + chunks). The control-plane
tables (eval_runs, eval_results, prompt_versions, ...) are introduced in Week 3
alongside Alembic migrations. For now we rely on SQLModel.metadata.create_all
plus an init.sql that enables the pgvector extension.
"""
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.config import settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(SQLModel, table=True):
    __tablename__ = "corpus_documents"

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)          # filename / origin
    title: str
    doc_version: str = Field(default="v1")   # bump to invalidate cache later
    created_at: datetime = Field(default_factory=_utcnow)


class Chunk(SQLModel, table=True):
    __tablename__ = "corpus_chunks"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(foreign_key="corpus_documents.id", index=True)
    chunk_index: int
    content: str
    token_count: int = 0
    # pgvector column; dimensionality must match the embedding model.
    embedding: list[float] = Field(
        sa_column=Column(Vector(settings.embedding_dim))
    )
    created_at: datetime = Field(default_factory=_utcnow)
