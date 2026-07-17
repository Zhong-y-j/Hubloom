import type { A2uiMessage } from "@/types/a2ui";
import { BASIC_CATALOG_ID } from "@/data/scenarios";

const A2UI_TAG_RE = /<a2ui-json>\s*([\s\S]*?)\s*<\/a2ui-json>/gi;

const MSG_KEYS = [
  "createSurface",
  "updateComponents",
  "updateDataModel",
  "deleteSurface",
] as const;

function isMessage(value: unknown): value is A2uiMessage {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const obj = value as Record<string, unknown>;
  const hits = MSG_KEYS.filter((k) => k in obj);
  return hits.length === 1;
}

function normalizeMessage(raw: Record<string, unknown>): A2uiMessage {
  return { ...raw, version: "v0.9.1" } as A2uiMessage;
}

function surfaceIdOf(msg: A2uiMessage): string | undefined {
  if ("createSurface" in msg) return msg.createSurface.surfaceId;
  if ("updateComponents" in msg) return msg.updateComponents.surfaceId;
  if ("updateDataModel" in msg) return msg.updateDataModel.surfaceId;
  if ("deleteSurface" in msg) return msg.deleteSurface.surfaceId;
  return undefined;
}

export function ensureCreateSurface(messages: A2uiMessage[]): A2uiMessage[] {
  if (messages.some((m) => "createSurface" in m)) return messages;
  const sid = messages.map(surfaceIdOf).find(Boolean);
  if (!sid) return messages;
  return [
    {
      version: "v0.9.1",
      createSurface: { surfaceId: sid, catalogId: BASIC_CATALOG_ID },
    },
    ...messages,
  ];
}

/** 稳定顺序：建面 → 组件 → 数据 → 删除 */
function sortMessages(messages: A2uiMessage[]): A2uiMessage[] {
  const rank = (m: A2uiMessage) => {
    if ("createSurface" in m) return 0;
    if ("updateComponents" in m) return 1;
    if ("updateDataModel" in m) return 2;
    return 3;
  };
  return [...messages].sort((a, b) => rank(a) - rank(b));
}

export function findMissingListDataHint(messages: A2uiMessage[]): string | null {
  const listPaths = new Set<string>();
  for (const m of messages) {
    if (!("updateComponents" in m)) continue;
    for (const c of m.updateComponents.components) {
      if (c.component !== "List") continue;
      const children = c.children as { path?: string } | string[] | undefined;
      if (children && !Array.isArray(children) && typeof children.path === "string") {
        listPaths.add(children.path);
      }
    }
  }
  if (!listPaths.size) return null;

  const dataPaths = new Set<string>();
  for (const m of messages) {
    if ("updateDataModel" in m && m.updateDataModel.path) {
      dataPaths.add(m.updateDataModel.path);
    }
  }

  const missing = [...listPaths].filter((p) => !dataPaths.has(p));
  if (!missing.length) return null;
  return (
    `List 绑定了 ${missing.join(", ")}，但消息里没有对应的 updateDataModel，` +
    `所以右侧是空的。请把含 /items（或对应 path）的 updateDataModel 一并粘贴，` +
    `或点「填入完整示例」。`
  );
}

/** 从文本中按括号匹配抽出多个顶层 `{...}` 对象。 */
function extractJsonObjects(text: string): unknown[] {
  const out: unknown[] = [];
  let i = 0;
  while (i < text.length) {
    if (text[i] !== "{") {
      i += 1;
      continue;
    }
    let depth = 0;
    let inStr = false;
    let esc = false;
    let end = -1;
    for (let j = i; j < text.length; j++) {
      const ch = text[j];
      if (inStr) {
        if (esc) esc = false;
        else if (ch === "\\") esc = true;
        else if (ch === '"') inStr = false;
        continue;
      }
      if (ch === '"') {
        inStr = true;
        continue;
      }
      if (ch === "{") depth += 1;
      else if (ch === "}") {
        depth -= 1;
        if (depth === 0) {
          end = j;
          break;
        }
      }
    }
    if (end < 0) break;
    const slice = text.slice(i, end + 1);
    try {
      out.push(JSON.parse(slice));
    } catch {
      // 跳过无法解析的片段
    }
    i = end + 1;
  }
  return out;
}

/**
 * 兼容 Python 风格：['{...}', "{...}"] 或 ["{...}", "{...}"]
 * 抽出引号内的 JSON 字符串再 parse。
 */
function extractPythonStyleStringList(text: string): unknown[] | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("[") || !trimmed.endsWith("]")) return null;
  // 至少像「列表里装着 JSON 字符串」
  if (!/\[\s*['"]\{/.test(trimmed)) return null;

  const inner = trimmed.slice(1, -1);
  const chunks: string[] = [];
  const re = /(['"])([\s\S]*?)\1/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(inner))) {
    const body = m[2];
    if (body.trim().startsWith("{")) chunks.push(body);
  }
  if (!chunks.length) return null;

  const out: unknown[] = [];
  for (const chunk of chunks) {
    try {
      out.push(JSON.parse(chunk));
    } catch (err) {
      throw new Error(`列表内某段 JSON 无效：${(err as Error).message}`);
    }
  }
  return out;
}

function coerceCandidates(raw: unknown[]): unknown[] {
  const out: unknown[] = [];
  for (const item of raw) {
    if (typeof item === "string") {
      try {
        out.push(JSON.parse(item));
      } catch {
        out.push(item);
      }
    } else {
      out.push(item);
    }
  }
  return out;
}

/**
 * 解析粘贴内容，支持：
 * - 单个 A2UI 消息对象 / 消息数组
 * - 多个 &lt;a2ui-json&gt; 块
 * - `--- block ---` 分隔的多段 JSON
 * - Python 风格 `['{...}', '{...}']`
 */
export function parsePastedA2ui(raw: string): {
  messages: A2uiMessage[];
  error?: string;
  hint?: string;
} {
  const text = (raw || "").trim();
  if (!text) return { messages: [], error: "内容为空" };

  let candidates: unknown[] = [];

  for (const match of text.matchAll(A2UI_TAG_RE)) {
    const inner = (match[1] || "").trim();
    if (!inner) continue;
    try {
      candidates.push(JSON.parse(inner));
    } catch (err) {
      return {
        messages: [],
        error: `解析 <a2ui-json> 失败：${(err as Error).message}`,
      };
    }
  }

  if (!candidates.length) {
    try {
      candidates = extractPythonStyleStringList(text) || [];
    } catch (err) {
      return { messages: [], error: String((err as Error).message || err) };
    }
  }

  if (!candidates.length) {
    try {
      const data = JSON.parse(text);
      candidates = Array.isArray(data) ? data : [data];
    } catch {
      candidates = extractJsonObjects(text);
    }
  }

  candidates = coerceCandidates(candidates);

  if (!candidates.length) {
    return {
      messages: [],
      error:
        "无法解析。请贴：① JSON 数组 [{...},{...}] ② 多个 <a2ui-json> ③ 或点「填入完整示例」。不要用 Python 单引号列表（已尽量兼容，但仍推荐标准 JSON）。",
    };
  }

  const messages: A2uiMessage[] = [];
  for (let i = 0; i < candidates.length; i++) {
    const item = candidates[i];
    if (!isMessage(item)) {
      return {
        messages: [],
        error: `第 ${i + 1} 条不是合法 A2UI 消息（需恰好含 createSurface / updateComponents / updateDataModel / deleteSurface 之一）`,
      };
    }
    messages.push(normalizeMessage(item as Record<string, unknown>));
  }

  const normalized = sortMessages(ensureCreateSurface(messages));
  return {
    messages: normalized,
    hint: findMissingListDataHint(normalized) || undefined,
  };
}

export const PASTE_DEMO_FULL = `<a2ui-json>
{"version":"v0.9","createSurface":{"surfaceId":"clickable-list-example","catalogId":"https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"}}
</a2ui-json>
<a2ui-json>
{"version":"v0.9","updateComponents":{"surfaceId":"clickable-list-example","components":[{"id":"root","component":"Column","children":["list-container"]},{"id":"list-container","component":"List","children":{"componentId":"list-item-template","path":"/items"},"direction":"vertical"},{"id":"list-item-template","component":"Row","children":["item-text","item-button"],"align":"center"},{"id":"item-text","component":"Text","text":{"path":"text"}},{"id":"button-text","component":"Text","text":"点击我"},{"id":"item-button","component":"Button","child":"button-text","action":{"event":{"name":"on_item_click","context":{"item_id":{"path":"id"}}}}}]}}
</a2ui-json>
<a2ui-json>
{"version":"v0.9","updateDataModel":{"surfaceId":"clickable-list-example","path":"/items","value":[{"id":"item-1","text":"第一项"},{"id":"item-2","text":"第二项"}]}}
</a2ui-json>
`;
