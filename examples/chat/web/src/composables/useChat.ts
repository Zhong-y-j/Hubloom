import { computed, ref } from "vue";
import type {
  AgentPhase,
  AnswerPart,
  ChatMessage,
  HistoryMessage,
  ToolBlock,
} from "@/types/chat";
import type { A2uiMessage } from "@/types/a2ui";

const STORAGE_SESSION = "cortex_session_key";
const STORAGE_TOKEN = "cortex_mcp_token";
const STORAGE_PRESENT = "cortex_present_mode";

export type PresentMode = "auto" | "a2ui" | "markdown";

function loadPresentMode(): PresentMode {
  const raw = (localStorage.getItem(STORAGE_PRESENT) || "").trim().toLowerCase();
  if (raw === "a2ui" || raw === "markdown" || raw === "auto") return raw;
  return "auto";
}

function uuid(): string {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `id-${Date.now().toString(36)}`;
}

function normalizeSessionKey(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("mem:") && trimmed.endsWith(":default")) {
    return trimmed.slice(4, -":default".length);
  }
  return trimmed;
}

function coerceAnswerParts(raw: unknown): AnswerPart[] | undefined {
  if (!Array.isArray(raw) || !raw.length) return undefined;
  const out: AnswerPart[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const obj = item as Record<string, unknown>;
    const kind = String(obj.type || "").trim();
    if (kind === "text") {
      const text = String(obj.text || "").trim();
      if (!text) continue;
      const channelRaw = String(obj.channel || "").trim();
      const channel =
        channelRaw === "a2ui" || channelRaw === "markdown"
          ? channelRaw
          : undefined;
      out.push(channel ? { type: "text", text, channel } : { type: "text", text });
    } else if (kind === "a2ui") {
      out.push({ type: "a2ui" });
    }
  }
  return out.length ? out : undefined;
}

function a2uiProseFromParts(parts: AnswerPart[] | undefined): string | undefined {
  if (!parts?.length) return undefined;
  const prose = parts
    .filter(
      (p): p is { type: "text"; text: string; channel?: "markdown" | "a2ui" } =>
        p.type === "text" && p.channel === "a2ui",
    )
    .map((p) => p.text)
    .join("\n\n")
    .trim();
  return prose || undefined;
}

function appendTextDelta(
  msg: ChatMessage,
  delta: string,
  channel: "markdown" | "a2ui" = "markdown",
) {
  if (channel === "markdown") {
    msg.content += delta;
  } else {
    msg.a2uiProse = (msg.a2uiProse || "") + delta;
  }
  const parts = msg.answerParts ? [...msg.answerParts] : [];
  const last = parts[parts.length - 1];
  const lastChannel =
    last?.type === "text" ? last.channel || "markdown" : undefined;
  if (last?.type === "text" && lastChannel === channel) {
    parts[parts.length - 1] = {
      type: "text",
      text: last.text + delta,
      channel,
    };
  } else {
    parts.push({ type: "text", text: delta, channel });
  }
  msg.answerParts = parts;
}

function ensureA2uiPart(msg: ChatMessage) {
  const parts = msg.answerParts ? [...msg.answerParts] : [];
  if (parts[parts.length - 1]?.type !== "a2ui") {
    parts.push({ type: "a2ui" });
    msg.answerParts = parts;
  }
}

function parseSseChunk(buffer: string): {
  events: Array<{ event: string; data: Record<string, unknown> }>;
  rest: string;
} {
  const events: Array<{ event: string; data: Record<string, unknown> }> = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() || "";
  for (const part of parts) {
    if (!part.trim()) continue;
    let eventName = "message";
    let dataLine = "";
    for (const line of part.split("\n")) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim();
      if (line.startsWith("data:")) dataLine += line.slice(5).trim();
    }
    if (dataLine) {
      try {
        events.push({
          event: eventName,
          data: JSON.parse(dataLine) as Record<string, unknown>,
        });
      } catch {
        events.push({ event: eventName, data: { raw: dataLine } });
      }
    }
  }
  return { events, rest };
}

export function useChat() {
  const token = ref(localStorage.getItem(STORAGE_TOKEN) || "");
  const sessionId = ref(
    normalizeSessionKey(localStorage.getItem(STORAGE_SESSION) || "") ||
      `web-${uuid()}`
  );
  const messages = ref<ChatMessage[]>([]);
  const busy = ref(false);
  const status = ref("就绪");
  const route = ref("");
  const agentPhase = ref<AgentPhase>(null);
  const showTools = ref(true);
  /** 呈现模式：随请求 body.present_mode 传给后端 */
  const presentMode = ref<PresentMode>(loadPresentMode());
  const mcpReady = ref<boolean | null>(null);
  const mcpDetail = ref("");

  /** 会话 ID 即可发消息；业务 Token 可选（部分 OpenAPI 无需鉴权） */
  const ready = computed(() => Boolean(normalizeSessionKey(sessionId.value)));

  function persist() {
    localStorage.setItem(STORAGE_TOKEN, token.value.trim());
    localStorage.setItem(
      STORAGE_SESSION,
      normalizeSessionKey(sessionId.value)
    );
    localStorage.setItem(STORAGE_PRESENT, presentMode.value);
  }

  function buildHeaders(): HeadersInit {
    const key = normalizeSessionKey(sessionId.value);
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (key) headers["X-Session-Id"] = key;
    const t = token.value.trim();
    if (t) {
      headers["X-MCP-Token"] = t;
      headers["Authorization"] = `Bearer ${t}`;
    }
    return headers;
  }

  function newSession() {
    sessionId.value = `web-${uuid()}`;
    messages.value = [];
    route.value = "";
    agentPhase.value = null;
    persist();
    status.value = ready.value ? "就绪" : "请填写用户 ID";
  }

  async function refreshMcpStatus() {
    try {
      const res = await fetch("/v1/mcp/status");
      if (!res.ok) {
        mcpReady.value = false;
        mcpDetail.value = `HTTP ${res.status}`;
        return;
      }
      const data = (await res.json()) as {
        mcp_ready?: boolean;
        detail?: string;
        tool_count?: number;
      };
      mcpReady.value = Boolean(data.mcp_ready);
      mcpDetail.value =
        data.detail ||
        (data.mcp_ready
          ? `已连接 · ${data.tool_count ?? 0} 工具`
          : "MCP 未就绪");
    } catch (err) {
      mcpReady.value = false;
      mcpDetail.value =
        err instanceof Error ? err.message : "无法连接后端 /v1/mcp/status";
    }
  }

  async function loadHistory() {
    if (!ready.value) return;
    persist();
    const key = normalizeSessionKey(sessionId.value);
    try {
      const res = await fetch(
        `/v1/chat/history?session_id=${encodeURIComponent(key)}`,
        { headers: buildHeaders() }
      );
      if (!res.ok) return;
      const data = (await res.json()) as { messages?: HistoryMessage[] };
      const rows = data.messages || [];
      messages.value = rows.map((m) => ({
        id: uuid(),
        role: m.role,
        content: m.content || "",
        thought: m.thought || undefined,
        tools: (m.tools as ToolBlock[] | null) || undefined,
        a2uiMessages:
          Array.isArray(m.a2ui) && m.a2ui.length
            ? (m.a2ui as A2uiMessage[])
            : undefined,
        answerParts: coerceAnswerParts(m.answer_parts),
        a2uiProse: a2uiProseFromParts(coerceAnswerParts(m.answer_parts)),
      }));
      status.value = rows.length ? `已加载 ${rows.length} 条历史` : "就绪";
    } catch {
      /* ignore */
    }
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy.value || !ready.value) return;

    persist();
    busy.value = true;
    agentPhase.value = "understanding";
    status.value = "理解中…";
    route.value = "";

    messages.value.push({
      id: uuid(),
      role: "user",
      content: message,
    });

    const assistant: ChatMessage = {
      id: uuid(),
      role: "assistant",
      content: "",
      thought: "",
      tools: [],
      streaming: true,
    };
    messages.value.push(assistant);
    const idx = messages.value.length - 1;

    const key = normalizeSessionKey(sessionId.value);

    try {
      const res = await fetch("/v1/chat", {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify({
          message,
          session_id: key || null,
          stream: true,
          present_mode: presentMode.value,
        }),
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }
      if (!res.body) throw new Error("无响应流");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;

        for (const { event, data } of parsed.events) {
          const current = messages.value[idx];
          if (!current) continue;

          if (event === "phase") {
            const phase = String(data.phase || "").trim();
            if (phase === "thinking") {
              agentPhase.value = "thinking";
              status.value = "思考中…";
            } else if (phase === "presenting") {
              agentPhase.value = "presenting";
              status.value = "呈现决策中…";
            } else if (phase === "replying") {
              agentPhase.value = "replying";
              status.value = "回复中…";
            }
            if (data.route) route.value = String(data.route);
          } else if (event === "thought_delta") {
            current.thought = (current.thought || "") + String(data.delta || "");
          } else if (event === "text_delta" && data.delta) {
            agentPhase.value = "replying";
            const sourceRaw = String(data.source || "").trim().toLowerCase();
            const channel: "markdown" | "a2ui" =
              sourceRaw === "a2ui" ? "a2ui" : "markdown";
            appendTextDelta(current, String(data.delta), channel);
          } else if (event === "a2ui") {
            const raw = data.messages;
            if (Array.isArray(raw) && raw.length) {
              const batch = raw as A2uiMessage[];
              if (data.replace) {
                current.a2uiMessages = batch;
                current.a2uiReloadKey = (current.a2uiReloadKey || 0) + 1;
              } else {
                current.a2uiMessages = [
                  ...(current.a2uiMessages || []),
                  ...batch,
                ];
              }
              ensureA2uiPart(current);
            }
            agentPhase.value = "replying";
          } else if (event === "tool_call") {
            const toolName = String(data.tool_name || "tool");
            const block: ToolBlock = {
              title: `调用 · ${toolName}`,
              body: JSON.stringify(data.args || {}, null, 2),
            };
            current.tools = [...(current.tools || []), block];
            agentPhase.value = "thinking";
          } else if (event === "tool_result") {
            const toolName = String(data.tool_name || "tool");
            const block: ToolBlock = {
              title: `${data.is_error ? "失败" : "返回"} · ${toolName}`,
              body: String(data.result || ""),
            };
            current.tools = [...(current.tools || []), block];
          } else if (event === "turn_complete") {
            if (data.final_message != null) {
              current.content = String(data.final_message);
            }
            const parts = coerceAnswerParts(data.answer_parts);
            if (parts) {
              current.answerParts = parts;
              current.a2uiProse = a2uiProseFromParts(parts);
            }
            if (data.route) route.value = String(data.route);
            current.streaming = false;
          } else if (event === "error") {
            // recoverable=true 仅为告警，正文仍有效，不要整条标红
            if (!data.recoverable) {
              current.error = true;
              current.content =
                current.content || String(data.error || "未知错误");
              current.streaming = false;
            }
          }
        }
      }

      const last = messages.value[idx];
      if (last) last.streaming = false;
      agentPhase.value = null;
      status.value = "就绪";
    } catch (err) {
      const last = messages.value[idx];
      if (last) {
        last.error = true;
        last.streaming = false;
        last.content =
          last.content ||
          (err instanceof Error ? err.message : "请求失败");
      }
      agentPhase.value = null;
      status.value = "出错";
    } finally {
      busy.value = false;
      if (ready.value && status.value === "出错") {
        /* keep */
      } else if (ready.value) {
        status.value = "就绪";
      }
    }
  }

  return {
    token,
    sessionId,
    messages,
    busy,
    status,
    route,
    agentPhase,
    showTools,
    presentMode,
    mcpReady,
    mcpDetail,
    ready,
    persist,
    newSession,
    refreshMcpStatus,
    loadHistory,
    send,
  };
}
