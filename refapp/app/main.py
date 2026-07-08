"""Harbor reference app entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.chat import router as chat_router
from app.config import settings
from app.db import engine, init_db
from app.models import Chunk, Document


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Harbor Reference App", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/corpus/stats")
def corpus_stats() -> dict:
    with Session(engine) as session:
        docs = session.exec(select(func.count()).select_from(Document)).one()
        chunks = session.exec(select(func.count()).select_from(Chunk)).one()
    return {"documents": docs, "chunks": chunks, "embedding_model": settings.embedding_model}
