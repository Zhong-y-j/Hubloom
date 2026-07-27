"""企微 UserId → 业务 Bearer Token（HTTP 可配置）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger


class TokenResolveError(Exception):
    """换 Token 失败。"""

    def __init__(self, message: str, *, unbound: bool = False) -> None:
        super().__init__(message)
        self.unbound = unbound


@dataclass
class TokenResolveConfig:
    """业务换 Token 接口描述。"""

    url: str
    method: str = "POST"
    # JSON 字符串模板，可用 {wecom_userid}
    body_template: str = '{"wecomUserId":"{wecom_userid}"}'
    # 可选服务账号：替换 headers 里的 {service_token}
    service_token: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # 响应 JSON 点路径，默认 accessToken；也尝试 data.accessToken
    token_path: str = "accessToken"
    unbound_http_statuses: tuple[int, ...] = (404,)
    unbound_codes: tuple[str, ...] = ()
    timeout_s: float = 10.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TokenResolveConfig | None:
        if not isinstance(raw, dict):
            return None
        url = str(raw.get("url") or "").strip()
        if not url:
            return None
        method = str(raw.get("method") or "POST").strip().upper() or "POST"
        body = raw.get("body_template")
        body_template = (
            str(body)
            if body is not None
            else '{"wecomUserId":"{wecom_userid}"}'
        )
        headers_raw = raw.get("headers") or {}
        headers: dict[str, str] = {}
        if isinstance(headers_raw, dict):
            for k, v in headers_raw.items():
                if k is None or v is None:
                    continue
                headers[str(k)] = str(v)
        statuses = raw.get("unbound_http_statuses")
        if isinstance(statuses, list):
            unbound_http = tuple(int(x) for x in statuses)
        else:
            unbound_http = (404,)
        codes = raw.get("unbound_codes") or []
        if not isinstance(codes, list):
            codes = []
        unbound_codes = tuple(str(c).strip() for c in codes if str(c).strip())
        timeout = raw.get("timeout_s")
        try:
            timeout_s = float(timeout) if timeout is not None else 10.0
        except (TypeError, ValueError):
            timeout_s = 10.0
        return cls(
            url=url,
            method=method,
            body_template=body_template,
            service_token=(
                str(raw["service_token"]).strip()
                if raw.get("service_token") is not None
                else None
            )
            or None,
            headers=headers,
            token_path=str(raw.get("token_path") or "accessToken").strip()
            or "accessToken",
            unbound_http_statuses=unbound_http,
            unbound_codes=unbound_codes,
            timeout_s=timeout_s,
        )


def _dig(data: Any, path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _extract_token(payload: Any, token_path: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    candidates = [token_path, "accessToken", "data.accessToken", "token", "data.token"]
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        val = _dig(payload, path)
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return None


def _is_unbound_payload(payload: Any, unbound_codes: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict) or not unbound_codes:
        return False
    for key in ("code", "errorCode", "errCode", "status"):
        if key not in payload:
            continue
        if str(payload.get(key)).strip() in unbound_codes:
            return True
    return False


class BusinessTokenResolver:
    """按配置调用业务 HTTP 接口，解析 Bearer Token。"""

    def __init__(self, cfg: TokenResolveConfig) -> None:
        self.cfg = cfg

    async def resolve(self, wecom_userid: str) -> str:
        uid = (wecom_userid or "").strip()
        if not uid:
            raise TokenResolveError("wecom_userid 为空", unbound=True)

        url = self.cfg.url.replace("{wecom_userid}", uid)
        headers = {
            k: v.replace("{service_token}", self.cfg.service_token or "").replace(
                "{wecom_userid}", uid
            )
            for k, v in self.cfg.headers.items()
        }
        body_text = self.cfg.body_template.replace("{wecom_userid}", uid)
        method = self.cfg.method.upper()

        try:
            async with httpx.AsyncClient(timeout=self.cfg.timeout_s) as client:
                if method == "GET":
                    if "{wecom_userid}" not in self.cfg.url and "wecomUserId" not in url:
                        sep = "&" if "?" in url else "?"
                        url = f"{url}{sep}wecomUserId={uid}"
                    resp = await client.get(url, headers=headers)
                else:
                    try:
                        json_body = json.loads(body_text) if body_text.strip() else {}
                    except json.JSONDecodeError:
                        json_body = {"wecomUserId": uid}
                    if not any(k.lower() == "content-type" for k in headers):
                        headers = {**headers, "Content-Type": "application/json"}
                    resp = await client.request(
                        method, url, headers=headers, json=json_body
                    )
        except httpx.HTTPError as exc:
            logger.warning(
                "wecom token_resolve network error | detail={}",
                str(exc)[:200],
            )
            raise TokenResolveError("账号服务暂时不可用，请稍后重试") from exc

        payload: Any = None
        try:
            payload = resp.json()
        except Exception:
            payload = None

        if resp.status_code in self.cfg.unbound_http_statuses or _is_unbound_payload(
            payload, self.cfg.unbound_codes
        ):
            raise TokenResolveError(
                "企微账号尚未绑定业务账号，请联系管理员完成绑定后再试。",
                unbound=True,
            )

        if resp.status_code >= 400:
            raise TokenResolveError(
                f"换取业务 Token 失败（HTTP {resp.status_code}）"
            )

        token = _extract_token(payload, self.cfg.token_path)
        if not token:
            raise TokenResolveError("业务接口未返回 accessToken")
        return token
