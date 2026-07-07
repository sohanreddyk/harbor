FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Cache the fastembed/ONNX model download on a mounted volume.
    HF_HOME=/models \
    FASTEMBED_CACHE_PATH=/models

# System deps kept minimal; psycopg[binary] and fastembed ship wheels.
COPY pyproject.toml ./
COPY app ./app
COPY scripts ./scripts
COPY data ./data

RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
