"""Local embeddings via fastembed (ONNX runtime, no torch).

We deliberately avoid sentence-transformers/torch here: fastembed keeps the
image small and cold-start fast, which matters for a self-hostable system.

BGE models are asymmetric — queries are embedded with a retrieval instruction
prefix, passages are embedded raw. Getting this right measurably improves
recall, so it lives in one place.
"""
from functools import lru_cache

from fastembed import TextEmbedding

from app.config import settings

# Recommended query instruction for bge-*-en-v1.5.
_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    # Downloads the ONNX model on first use (~130MB) and caches it.
    return TextEmbedding(model_name=settings.embedding_model)


def embed_passages(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _model().embed(texts)]


def embed_query(query: str) -> list[float]:
    text = _QUERY_INSTRUCTION + query
    return next(_model().embed([text])).tolist()
