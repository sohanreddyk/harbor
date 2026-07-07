"""Async client for the Harbor gateway (OpenAI-compatible SSE)."""
import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings


async def stream_chat(messages: list[dict], model: str) -> AsyncIterator[str]:
    """Yield content deltas from the gateway's streaming chat endpoint.

    The gateway speaks the OpenAI SSE format (`data: {...}` lines terminated by
    `data: [DONE]`), so this parser also works against OpenAI directly if the
    gateway is ever bypassed.
    """
    payload = {"model": model, "messages": messages, "stream": True}
    url = settings.gateway_url.rstrip("/") + "/v1/chat/completions"

    timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {}).get("content")
                    if delta:
                        yield delta
