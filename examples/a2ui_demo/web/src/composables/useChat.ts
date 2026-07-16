import { computed, ref } from "vue";
import type {
  AgentPhase,
  ChatMessage,
  HistoryMessage,
  ToolBlock,
} from "@/types/chat";
import type { A2uiMessage } from "@/types/a2ui";

const STORAGE_SESSION = "cortex_session_key";
const STORAGE_TOKEN = "cortex_mcp_token";

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
  const status = ref("请填写 Token 与用户 ID");
  const route = ref("");
  const agentPhase = ref<AgentPhase>(null);
  const showTools = ref(true);
  const mcpReady = ref<boolean | null>(null);
  const mcpDetail = ref("");

  const ready = computed(
    () => Boolean(token.value.trim() && normalizeSessionKey(sessionId.value))
  );

  function persist() {
    localStorage.setItem(STORAGE_TOKEN, token.value.trim());
    localStorage.setItem(
      STORAGE_SESSION,
      normalizeSessionKey(sessionId.value)
    );
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
    status.value = ready.value ? "就绪" : "请填写 Token 与用户 ID";
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
            } else if (phase === "replying") {
              agentPhase.value = "replying";
              status.value = "回复中…";
            }
            if (data.route) route.value = String(data.route);
          } else if (event === "thought_delta") {
            current.thought = (current.thought || "") + String(data.delta || "");
          } else if (event === "text_delta" && data.delta) {
            agentPhase.value = "replying";
            current.content += String(data.delta);
          } else if (event === "a2ui") {
            const raw = data.messages;
            if (Array.isArray(raw) && raw.length) {
              current.a2uiMessages = raw as A2uiMessage[];
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
            if (data.final_message != null && data.final_message !== "") {
              // 与后端权威 Markdown 对齐（已切掉 A2UI JSON）
              current.content = String(data.final_message);
            }
            if (data.route) route.value = String(data.route);
            current.streaming = false;
          } else if (event === "error") {
            current.error = true;
            current.content =
              current.content || String(data.error || "未知错误");
            current.streaming = false;
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
