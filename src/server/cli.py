"""Hubloom CLI：``hubloom serve`` / ``python -m server``。"""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hubloom",
        description="Hubloom 企业 Agent 平台 CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve_p = sub.add_parser(
        "serve",
        help="启动 Hubloom HTTP API（无 A2UI / AG-UI）",
    )
    serve_p.add_argument(
        "--config",
        "-c",
        default="config/env.yaml",
        help="配置文件路径（默认 config/env.yaml）",
    )
    serve_p.add_argument("--host", default=None, help="覆盖配置 http.host")
    serve_p.add_argument("--port", type=int, default=None, help="覆盖配置 http.port")
    serve_p.add_argument(
        "--reload",
        action="store_true",
        help="开发热重载（仅本地）",
    )

    args = parser.parse_args(argv)
    if args.cmd == "serve":
        _cmd_serve(args)
    else:
        parser.error(f"未知命令: {args.cmd}")


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from config import HubloomConfig
    from server.app import create_app

    cfg_path = Path(args.config).resolve()
    if not cfg_path.is_file():
        raise SystemExit(f"配置文件不存在: {cfg_path}")

    cfg = HubloomConfig.from_file(cfg_path)
    host = (args.host or cfg.api_host or "0.0.0.0").strip() or "0.0.0.0"
    port = int(args.port if args.port is not None else (cfg.api_port or 8765))
    reload = bool(args.reload or cfg.api_reload)

    app = create_app(config_path=cfg_path)
    print(f"Hubloom serve  http://{host}:{port}")
    print(f"  config={cfg_path}")
    print(f"  docs=http://{host}:{port}/docs")
    print("  API: POST /v1/chat  POST /v1/chat/resume  GET /v1/chat/history")
    if reload:
        # reload 需要 import string；开发请用 uvicorn 命令行
        print("提示: --reload 在本入口下忽略，请用: uvicorn server.app:create_app --factory")
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
