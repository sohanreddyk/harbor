"""Database models.

Retrieval tables (documents + chunks) plus the Week 3 control-plane tables
(eval suites, test cases, runs, results). All are created via
SQLModel.metadata.create_all; since these are new tables, no migration tool is
needed yet (Alembic is introduced when existing tables start changing).
"""
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column
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


# --------------------------------------------------------------------------
# Control plane (Week 3): evaluation suites, cases, runs, and results.
# --------------------------------------------------------------------------


class EvalSuite(SQLModel, table=True):
    __tablename__ = "eval_suites"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class TestCase(SQLModel, table=True):
    __tablename__ = "eval_test_cases"

    id: int | None = Field(default=None, primary_key=True)
    suite_id: int = Field(foreign_key="eval_suites.id", index=True)
    question: str
    gold_answer: str
    # Keywords that a grounded answer should contain, and the source documents
    # it should be drawn from. Used by the keyword-coverage / citation checks.
    gold_keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    gold_sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"

    id: int | None = Field(default=None, primary_key=True)
    suite_id: int = Field(foreign_key="eval_suites.id", index=True)
    prompt_version: str = "v1"
    model: str = ""
    top_k: int = 4
    git_sha: str | None = None
    status: str = "running"  # running | done | failed
    num_cases: int = 0
    mean_score: float | None = None
    # Per-evaluator mean score, e.g. {"keyword_coverage": 0.82, ...}.
    per_evaluator: dict = Field(default_factory=dict, sa_column=Column(JSON))
    baseline_run_id: int | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: datetime | None = None


class EvalResult(SQLModel, table=True):
    __tablename__ = "eval_results"

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="eval_runs.id", index=True)
    test_case_id: int = Field(foreign_key="eval_test_cases.id", index=True)
    evaluator_name: str = Field(index=True)
    score: float | None = None       # None = evaluator skipped (e.g. no keywords)
    passed: bool | None = None
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON))
