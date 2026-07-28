"""企业微信 IM 真机联调（不经 Agent）：主动推送 / 回调回声。

两种模式：

1. **send** — 本机 → 企微：用 ``im.wecom`` 配置取 token，向指定成员发一条应用消息。
2. **echo** — 企微 → 本机 → 企微：起一个最小回调服务，解密收到的消息并打印，
   再主动推一条固定回复（**不**换业务票、**不**跑 Agent）。

用法（仓库根目录）::

    # 推一条到企微（把 UserId 换成你在通讯录里的账号）
    WECOM_TO_USER=ZhangSan \\
      PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py send

    # 或显式传参
    PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py send --to ZhangSan \\
      --text "Hubloom IM 联调：你好"

    # 收消息并原路回一条（需公网 HTTPS 指到本服务，例如 cloudflared）
    PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py echo --port 8765

配置读 ``HUBLOOM_CONFIG`` 或默认 ``config/env.yaml`` 里的 ``im.wecom.*``。

起临时公网隧道 cloudflared tunnel --url http://127.0.0.1:8765，终端出现类似 https://xxxx.trycloudflare.com 的地址
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, Response
from uvicorn import run as uvicorn_run

from config import HubloomConfig
from im.wecom.client import WeComAppClient
from im.wecom.crypto import WeComCrypto, parse_message_xml


def _config_path() -> Path:
    env = (os.environ.get("HUBLOOM_CONFIG") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path("config/env.yaml").resolve()


def _load_wecom_cfg() -> HubloomConfig:
    path = _config_path()
    if not path.is_file():
        raise SystemExit(f"找不到配置文件: {path}")
    cfg = HubloomConfig.from_file(path)
    if not cfg.wecom_enable:
        raise SystemExit("请在配置里设 im.wecom.enable: true")
    missing = [
        name
        for name, ok in (
            ("corp_id", bool(cfg.wecom_corp_id)),
            ("corp_secret", bool(cfg.wecom_corp_secret)),
            ("agent_id", cfg.wecom_agent_id is not None),
            ("token", bool(cfg.wecom_token)),
            ("encoding_aes_key", bool(cfg.wecom_encoding_aes_key)),
        )
        if not ok
    ]
    if missing:
        raise SystemExit(f"im.wecom 缺少配置: {', '.join(missing)}")
    return cfg


def _make_client(cfg: HubloomConfig) -> WeComAppClient:
    assert (
        cfg.wecom_corp_id and cfg.wecom_corp_secret and cfg.wecom_agent_id is not None
    )
    return WeComAppClient(
        corp_id=cfg.wecom_corp_id,
        corp_secret=cfg.wecom_corp_secret,
        agent_id=cfg.wecom_agent_id,
    )


def _make_crypto(cfg: HubloomConfig) -> WeComCrypto:
    assert cfg.wecom_token and cfg.wecom_encoding_aes_key and cfg.wecom_corp_id
    return WeComCrypto(
        cfg.wecom_token,
        cfg.wecom_encoding_aes_key,
        cfg.wecom_corp_id,
    )


async def cmd_send(*, to_user: str, text: str) -> None:
    cfg = _load_wecom_cfg()
    userid = (to_user or "").strip()
    if not userid:
        raise SystemExit(
            "请指定接收人企微 UserId：\n"
            "  WECOM_TO_USER=你的UserId PYTHONPATH=src .venv/bin/python tests/test_im_wecom.py send\n"
            "  或 --to 你的UserId"
        )

    client = _make_client(cfg)
    print("【模式】 send（本机 → 企微，不经 Agent）")
    print("【配置】", _config_path())
    print(
        "【应用】 agent_id=",
        cfg.wecom_agent_id,
        "corp_id=",
        (cfg.wecom_corp_id or "")[:6] + "…",
    )
    print("【接收人】", userid)

    token = await client.get_access_token()
    print("【gettoken】 ok，access_token 长度", len(token))

    body = (text or "").strip() or (
        f"Hubloom IM 联调（无 Agent）\n时间：{datetime.now().isoformat(timespec='seconds')}"
    )
    print("【发送】 markdown …")
    result = await client.send_markdown(userid=userid, content=body)
    print("【结果】", result)
    print("请到企业微信里看该应用是否收到上述消息。")


def cmd_echo(*, host: str, port: int) -> None:
    cfg = _load_wecom_cfg()
    crypto = _make_crypto(cfg)
    client = _make_client(cfg)
    app = FastAPI(title="Hubloom WeCom echo (no Agent)")

    @app.get("/v1/im/wecom/callback")
    async def verify(
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ) -> Response:
        try:
            plain = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        except Exception as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        print("【URL 验证】 ok，echo=", plain[:40])
        return Response(content=plain, media_type="text/plain")

    @app.post("/v1/im/wecom/callback")
    async def on_message(
        request: Request,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
    ) -> Response:
        body = await request.body()
        try:
            plain = crypto.decrypt_message(msg_signature, timestamp, nonce, body)
            msg = parse_message_xml(plain)
        except Exception as exc:
            print("【解密失败】", exc)
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        userid = (msg.get("FromUserName") or "").strip()
        msg_type = (msg.get("MsgType") or "").strip()
        content = (msg.get("Content") or "").strip()
        msg_id = (msg.get("MsgId") or "").strip()
        print(
            "【收到】",
            {
                "FromUserName": userid,
                "MsgType": msg_type,
                "MsgId": msg_id,
                "Content": content[:200],
            },
        )

        # 不经 Agent：固定回一条，证明「收得到 + 发得回」
        if userid:
            reply = (
                f"Hubloom echo（无 Agent）已收到。\n"
                f"- 类型：{msg_type}\n"
                f"- 内容：{content or '（非文本或空）'}\n"
                f"- 时间：{datetime.now().isoformat(timespec='seconds')}"
            )

            async def _push() -> None:
                try:
                    await client.send_markdown(userid=userid, content=reply)
                    print("【回推】 markdown ok →", userid)
                except Exception as exc:
                    print("【回推失败】", exc)

            asyncio.create_task(_push())

        # 企微要求尽快空 200
        return Response(content=b"", media_type="text/plain")

    print("【模式】 echo（企微 → 本机解密打印 → 主动回推，不经 Agent）")
    print("【配置】", _config_path())
    print(f"【监听】 http://{host}:{port}/v1/im/wecom/callback")
    print(
        "请把企微「接收消息」URL 指到公网 HTTPS 的同一路径"
        "（本地可用 cloudflared tunnel）。"
    )
    print("保存配置后，在企微里给该应用发一条文字，本终端应打印【收到】并回推。")
    uvicorn_run(app, host=host, port=port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="企微 IM 真机联调（不经 Agent）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="本机主动向企微成员发一条消息")
    p_send.add_argument(
        "--to",
        default=(os.environ.get("WECOM_TO_USER") or "").strip(),
        help="企微成员 UserId（也可用环境变量 WECOM_TO_USER）",
    )
    p_send.add_argument("--text", default="", help="发送正文（默认带时间戳的联调文案）")

    p_echo = sub.add_parser("echo", help="起回调服务：收消息打印并固定回推")
    p_echo.add_argument("--host", default="0.0.0.0")
    p_echo.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)
    if args.cmd == "send":
        asyncio.run(cmd_send(to_user=args.to, text=args.text))
    elif args.cmd == "echo":
        cmd_echo(host=args.host, port=args.port)
    else:
        parser.error(f"未知命令: {args.cmd}")


if __name__ == "__main__":
    main(sys.argv[1:])
