# 独立部署：OpenAPI → MCP（Streamable HTTP）
# 构建（仓库根目录）:
#   docker build -f src/mcp_adapter/Dockerfile -t hubloom-mcp .
# 运行:
#   docker run --rm -p 8001:8001 \
#     -e MCP_SWAGGER_URL=https://.../swagger.json \
#     -e MCP_BASE_URL=https://api.example.com \
#     hubloom-mcp

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/app/src
ENV MCP_HTTP_HOST=0.0.0.0
ENV MCP_HTTP_PORT=8001
ENV MCP_HTTP_PATH=/mcp

EXPOSE 8001

CMD ["sh", "-c", "python -m mcp_adapter.server.worker --http --host ${MCP_HTTP_HOST} --port ${MCP_HTTP_PORT} --path ${MCP_HTTP_PATH}"]
