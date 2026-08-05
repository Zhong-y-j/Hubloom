# Hubloom Serve（产品 HTTP API）
# 构建：docker compose build serve
# 配置：运行时挂载 config/env.docker.yaml → /app/config/env.yaml

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY main.py ./
COPY skills ./skills

RUN pip install --no-cache-dir . \
    && mkdir -p /app/config /app/data /app/logs

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=12 \
  CMD curl -fsS --noproxy '*' http://127.0.0.1:8765/docs >/dev/null || exit 1

CMD ["python", "main.py", "serve", "--config", "config/env.yaml", "--host", "0.0.0.0", "--port", "8765"]
