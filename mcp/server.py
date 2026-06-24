import httpx
from fastmcp import FastMCP

SWAGGER_URL = "https://petstore3.swagger.io/api/v3/openapi.json"
BASE_URL = "https://petstore3.swagger.io/api/v3"
TOKEN = ""

headers = {}
if TOKEN:
    headers["Authorization"] = f"Bearer {TOKEN}"


async def fetch_spec():
    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        return (await client.get(SWAGGER_URL)).json()


if __name__ == "__main__":
    import asyncio

    spec = asyncio.run(fetch_spec())  # 只在这里用 asyncio

    api_client = httpx.AsyncClient(
        base_url=BASE_URL,
        headers=headers,
        trust_env=False,
        timeout=30.0,
    )
    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=api_client,
        name="My Swagger API",
    )
    mcp.run()  # 在 asyncio.run 外面调用
