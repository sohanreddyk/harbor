"""Reference RAG chat endpoint: retrieve -> prompt -> gateway -> SSE stream."""
import hashlib
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import settings
from app.db import get_session
from app.embeddings import embed_query
from app.gateway_client import stream_chat
from app.retrieval import RetrievedChunk, retrieve_with_vector

router = APIRouter(prefix="/api", tags=["chat"])

# Bump when SYSTEM_PROMPT changes so cached responses from the old prompt are
# not served for the new one (the gateway namespaces the cache by this value).
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "You are Harbor's documentation assistant. Answer the question using ONLY "
    "the provided context. Cite the sources you use with bracketed numbers such "
    "as [1] or [2]. If the context does not contain the answer, say you don't know."
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    top_k: int | None = None


def _build_messages(question: str, chunks: list[RetrievedChunk]) -> list[dict]:
    context_lines = [f"[{c.rank}] {c.content}" for c in chunks]
    user = "Context:\n" + "\n\n".join(context_lines) + f"\n\nQuestion: {question}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _context_hash(chunks: list[RetrievedChunk]) -> str:
    """Stable hash of the retrieved context.

    If the corpus changes such that different chunks are retrieved, this hash
    changes and the semantic cache correctly misses instead of serving a stale
    answer grounded in different sources.
    """
    joined = "\n".join(c.content for c in chunks)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, session: Session = Depends(get_session)):
    k = req.top_k or settings.top_k

    # Embed the query once; reuse for retrieval and the gateway cache key.
    qvec = await run_in_threadpool(embed_query, req.message)
    chunks = await run_in_threadpool(retrieve_with_vector, session, qvec, k)
    messages = _build_messages(req.message, chunks)

    harbor = {
        "embedding": qvec,
        "context_hash": _context_hash(chunks),
        "prompt_version": PROMPT_VERSION,
        "client_id": "refapp",
    }

    async def event_stream() -> AsyncIterator[str]:
        yield _sse(
            "sources",
            {
                "sources": [
                    {"rank": c.rank, "source": c.source, "title": c.title, "score": c.score}
                    for c in chunks
                ]
            },
        )
        meta: dict = {}
        try:
            async for delta in stream_chat(messages, settings.primary_model, harbor, meta_out=meta):
                yield _sse("token", {"content": delta})
        except Exception as exc:  # noqa: BLE001
            yield _sse("error", {"message": f"gateway error: {exc}"})
            return
        yield _sse("meta", meta)
        yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
