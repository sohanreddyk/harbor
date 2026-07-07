"""Database engine and session helpers."""
from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine, text

from app.config import settings

# pool_pre_ping guards against stale connections when Postgres restarts.
engine = create_engine(settings.database_url, pool_pre_ping=True, echo=False)


def init_db() -> None:
    """Ensure the pgvector extension and all tables exist.

    Idempotent: safe to call on every startup.
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
