FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CORTEX_API_HOST=0.0.0.0 \
    CORTEX_ENABLE_LONG_TERM_MEMORY=0 \
    CORTEX_MEMORY_DB=/app/data/memory.db \
    CORTEX_KB_DIR=/app/data/knowledge_db

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data /app/logs

EXPOSE 8000

CMD ["sh", "-c", "uvicorn agents.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
