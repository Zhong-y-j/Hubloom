import httpx
from fastmcp import FastMCP

from spec_loader import prepare_openapi

SWAGGER_URL = "https://petstore.swagger.io/v2/swagger.json"
BASE_URL = ""  # 留空则从 spec 自动推断，例如 https://petstore.swagger.io/v2
TOKEN = ""

headers = {}
if TOKEN:
    headers["Authorization"] = f"Bearer {TOKEN}"


if __name__ == "__main__":
    import asyncio

    spec, base_url = asyncio.run(
        prepare_openapi(SWAGGER_URL, base_url=BASE_URL or None)
    )

    api_client = httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        trust_env=False,
        timeout=30.0,
    )
    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=api_client,
        name="My Swagger API",
    )
    mcp.run()
