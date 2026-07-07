"""Reference RAG chat endpoint: retrieve -> prompt -> gateway -> SSE stream."""
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import settings
from app.db import get_session
from app.gateway_client import stream_chat
from app.retrieval import RetrievedChunk, retrieve

router = APIRouter(prefix="/api", tags=["chat"])

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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, session: Session = Depends(get_session)):
    k = req.top_k or settings.top_k
    chunks = await run_in_threadpool(retrieve, session, req.message, k)
    messages = _build_messages(req.message, chunks)

    async def event_stream() -> AsyncIterator[str]:
        # 1. Sources first so the UI can render citations immediately.
        yield _sse(
            "sources",
            {
                "sources": [
                    {"rank": c.rank, "source": c.source, "title": c.title, "score": c.score}
                    for c in chunks
                ]
            },
        )
        # 2. Stream tokens as they arrive from the gateway.
        try:
            async for delta in stream_chat(messages, settings.primary_model):
                yield _sse("token", {"content": delta})
        except Exception as exc:  # noqa: BLE001 - surface a clean error event
            yield _sse("error", {"message": f"gateway error: {exc}"})
            return
        # 3. Signal completion.
        yield _sse("done", {})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
