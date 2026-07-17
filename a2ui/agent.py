"""官网学习：SchemaManager 生成 prompt → OpenAI 兼容接口调用 LLM。

与 Hubloom Thought respond 共用 ``agents.a2ui_prompt.build_a2ui_schema_system_prompt``。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import yaml
from openai import OpenAI

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agents.a2ui_prompt import build_a2ui_schema_system_prompt

_A2UI_BLOCK_RE = re.compile(
    r"<a2ui-json>\s*(.*?)\s*</a2ui-json>",
    re.DOTALL | re.IGNORECASE,
)


def load_llm_settings() -> tuple[str, str | None, str]:
    """优先环境变量，其次仓库 config/env.yaml 的 llm 段。"""
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    model = (os.getenv("OPENAI_MODEL") or "").strip()

    cfg_path = _ROOT / "config" / "env.yaml"
    if cfg_path.is_file():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        llm = data.get("llm") or {}
        if not api_key:
            api_key = str(llm.get("api_key") or "").strip()
        if not base_url:
            raw = str(llm.get("base_url") or "").strip()
            base_url = raw or None
        if not model:
            model = str(llm.get("model") or "").strip()

    if not api_key or api_key == "...":
        raise SystemExit(
            "缺少 API Key：设置 OPENAI_API_KEY，或在 config/env.yaml 的 llm.api_key 填写"
        )
    if not model or model == "...":
        model = "gpt-4o-mini"
    return api_key, base_url, model


def extract_messages(content: str) -> list[dict]:
    messages: list[dict] = []
    for block in _A2UI_BLOCK_RE.findall(content):
        data = json.loads(block.strip())
        if isinstance(data, list):
            messages.extend(data)
        else:
            messages.append(data)
    return messages


def main() -> None:
    user_text = (
        " ".join(sys.argv[1:]).strip()
        or "请给我一个包含两项的可点击列表示例（带按钮）。"
    )
    api_key, base_url, model = load_llm_settings()
    system_prompt = build_a2ui_schema_system_prompt()

    client = OpenAI(api_key=api_key, base_url=base_url)
    print(f"[llm] model={model} base_url={base_url or '(default)'}")
    print(f"[user] {user_text}\n")
    print(f"[system prompt chars] {len(system_prompt)}\n")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.2,
    )
    content = (resp.choices[0].message.content or "").strip()
    print("===== LLM RESPONSE =====")
    print(content)

    messages = extract_messages(content)
    print(f"\n===== 解析到 {len(messages)} 条消息 =====")
    if not messages:
        print("未找到 <a2ui-json> 块。")
        return
    print(json.dumps(messages, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
