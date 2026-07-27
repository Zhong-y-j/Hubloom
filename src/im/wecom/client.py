"""企业微信应用消息客户端（gettoken + message/send）。"""

from __future__ import annotations

import time
from typing import Any

import httpx
from loguru import logger

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"


class WeComAppClient:
    """自建应用：取 access_token，向成员发送 text / markdown。"""

    def __init__(
        self,
        *,
        corp_id: str,
        corp_secret: str,
        agent_id: int | str,
        timeout_s: float = 15.0,
    ) -> None:
        self.corp_id = (corp_id or "").strip()
        self.corp_secret = (corp_secret or "").strip()
        self.agent_id = int(agent_id)
        self.timeout_s = timeout_s
        self._token: str | None = None
        self._token_expire_at: float = 0.0

    async def get_access_token(self, *, force: bool = False) -> str:
        now = time.time()
        if (
            not force
            and self._token
            and now < self._token_expire_at - 60
        ):
            return self._token
        url = f"{WECOM_API}/gettoken"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.get(
                url,
                params={"corpid": self.corp_id, "corpsecret": self.corp_secret},
            )
            data = resp.json()
        if int(data.get("errcode") or 0) != 0:
            raise RuntimeError(
                f"wecom gettoken failed: {data.get('errcode')} {data.get('errmsg')}"
            )
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise RuntimeError("wecom gettoken 未返回 access_token")
        expires = int(data.get("expires_in") or 7200)
        self._token = token
        self._token_expire_at = now + expires
        return token

    async def send_text(self, *, userid: str, content: str) -> dict[str, Any]:
        return await self._send(
            {
                "touser": userid,
                "msgtype": "text",
                "agentid": self.agent_id,
                "text": {"content": content},
            }
        )

    async def send_markdown(self, *, userid: str, content: str) -> dict[str, Any]:
        # 应用消息 markdown；过长时降级 text
        text = (content or "").strip()
        if len(text) > 2048:
            return await self.send_text(userid=userid, content=text[:2000] + "\n…(已截断)")
        return await self._send(
            {
                "touser": userid,
                "msgtype": "markdown",
                "agentid": self.agent_id,
                "markdown": {"content": text},
            }
        )

    async def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        token = await self.get_access_token()
        url = f"{WECOM_API}/message/send"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                url, params={"access_token": token}, json=body
            )
            data = resp.json()
        err = int(data.get("errcode") or 0)
        if err == 40014 or err == 42001:
            # token 失效，刷新一次
            token = await self.get_access_token(force=True)
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(
                    url, params={"access_token": token}, json=body
                )
                data = resp.json()
            err = int(data.get("errcode") or 0)
        if err != 0:
            logger.warning(
                "wecom message/send failed | errcode={} errmsg={}",
                err,
                data.get("errmsg"),
            )
            raise RuntimeError(
                f"wecom message/send failed: {err} {data.get('errmsg')}"
            )
        return data
