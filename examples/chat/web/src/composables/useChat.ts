import { computed, ref } from "vue";
import type {
  AgentPhase,
  ChatMessage,
  HistoryMessage,
  PendingAwait,
  ToolBlock,
} from "@/types/chat";

const STORAGE_SESSION = "hubloom_session_key";
const STORAGE_TOKEN = "hubloom_mcp_token";
const STORAGE_INCLUDE_THOUGHT = "hubloom_include_thought";

/** 网页对话默认可挂起等人 */
const WAIT_PROFILE = "interactive";

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
    if (!dataLine) continue;
    try {
      events.push({
        event: eventName,
        data: JSON.parse(dataLine) as Record<string, unknown>,
      });
    } catch {
      events.push({ event: eventName, data: { raw: dataLine } });
    }
  }
  return { events, rest };
}

export function useChat() {
  const token = ref(localStorage.getItem(STORAGE_TOKEN) || "");
  const sessionId = ref(
    normalizeSessionKey(localStorage.getItem(STORAGE_SESSION) || "") ||
      `web-${uuid()}`,
  );
  const messages = ref<ChatMessage[]>([]);
  const busy = ref(false);
  const status = ref("就绪");
  const agentPhase = ref<AgentPhase>(null);
  const showTools = ref(true);
  const includeThought = ref(
    localStorage.getItem(STORAGE_INCLUDE_THOUGHT) !== "0",
  );
  const mcpReady = ref<boolean | null>(null);
  const mcpDetail = ref("");
  const currentRunId = ref<string | null>(null);
  const pendingAwait = ref<PendingAwait | null>(null);

  const ready = computed(() => Boolean(normalizeSessionKey(sessionId.value)));
  const awaitingUser = computed(() => Boolean(pendingAwait.value));

  function persist() {
    localStorage.setItem(STORAGE_TOKEN, token.value.trim());
    localStorage.setItem(
      STORAGE_SESSION,
      normalizeSessionKey(sessionId.value),
    );
    localStorage.setItem(
      STORAGE_INCLUDE_THOUGHT,
      includeThought.value ? "1" : "0",
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
    agentPhase.value = null;
    currentRunId.value = null;
    pendingAwait.value = null;
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
        status?: string;
      };
      mcpReady.value = Boolean(data.mcp_ready);
      mcpDetail.value =
        data.detail ||
        (data.mcp_ready
          ? `已连接 · ${data.tool_count ?? 0} 工具`
          : data.status || "MCP 未就绪");
    } catch (err) {
      mcpReady.value = false;
      mcpDetail.value =
        err instanceof Error ? err.message : "无法连接 Hubloom Serve /v1/mcp/status";
    }
  }

  async function loadHistory() {
    if (!ready.value) return;
    persist();
    const key = normalizeSessionKey(sessionId.value);
    const qs = new URLSearchParams({ session_id: key });
    if (includeThought.value) qs.set("include_thought", "true");
    try {
      const res = await fetch(`/v1/chat/history?${qs.toString()}`, {
        headers: buildHeaders(),
      });
      if (!res.ok) return;
      const data = (await res.json()) as { messages?: HistoryMessage[] };
      const rows = data.messages || [];
      messages.value = rows.map((m) => ({
        id: uuid(),
        role: m.role,
        content: m.content || "",
        source: m.source || undefined,
        thought: includeThought.value
          ? m.thought || undefined
          : undefined,
        tools: Array.isArray(m.tools) && m.tools.length
          ? m.tools.map((t) => ({
              title: t.title || "tool",
              body: t.body || "",
            }))
          : undefined,
      }));
      pendingAwait.value = null;
      status.value = rows.length ? `已加载 ${rows.length} 条历史` : "就绪";
    } catch {
      /* ignore */
    }
  }

  function applySseEvent(
    event: string,
    data: Record<string, unknown>,
    current: ChatMessage,
  ) {
    if (event === "run_started") {
      const rid = String(data.run_id || "").trim();
      if (rid) currentRunId.value = rid;
      agentPhase.value = "deciding";
      status.value = "处理中…";
      return;
    }

    if (event === "phase") {
      const phase = String(data.phase || "").trim();
      if (phase === "thinking" || phase === "decide") {
        agentPhase.value = "deciding";
        status.value = "决策中…";
      } else if (phase === "acting" || phase === "execute") {
        agentPhase.value = "acting";
        status.value = "执行中…";
      } else if (phase === "replying") {
        agentPhase.value = "replying";
        status.value = "回复中…";
      }
      return;
    }

    if (event === "thought_delta") {
      current.thought = (current.thought || "") + String(data.delta || "");
      agentPhase.value = "deciding";
      return;
    }

    if (event === "text_delta") {
      const delta = String(data.delta || "");
      if (!delta) return;
      agentPhase.value = "replying";
      current.content += delta;
      return;
    }

    if (event === "final_answer") {
      const content = String(data.content || "");
      if (content) current.content = content;
      agentPhase.value = "replying";
      return;
    }

    if (event === "tool_call") {
      const toolName = String(data.tool_name || "tool");
      const block: ToolBlock = {
        title: `调用 · ${toolName}`,
        body: JSON.stringify(data.args || {}, null, 2),
      };
      current.tools = [...(current.tools || []), block];
      agentPhase.value = "acting";
      status.value = `调用 ${toolName}…`;
      return;
    }

    if (event === "tool_result") {
      const toolName = String(data.tool_name || "tool");
      const block: ToolBlock = {
        title: `${data.is_error ? "失败" : "返回"} · ${toolName}`,
        body: String(data.result || ""),
      };
      current.tools = [...(current.tools || []), block];
      return;
    }

    if (event === "step") {
      const action = String(data.action || "");
      if (action) status.value = `步骤 · ${action}`;
      return;
    }

    if (event === "policy_reject") {
      const reason = String(data.reason || data.code || "规程拒绝");
      status.value = `规程拦截：${reason}`;
      return;
    }

    if (event === "awaiting_user") {
      const runId = String(data.await_run_id || data.run_id || "").trim();
      const awaitToken = String(data.await_token || "").trim();
      const prompt = String(data.prompt || "").trim();
      const kind = String(data.kind || "ask").trim() || "ask";
      pendingAwait.value = {
        runId,
        awaitToken,
        kind,
        prompt,
      };
      if (prompt) {
        if (!current.content.trim()) {
          current.content = prompt;
          current.awaitPrompt = true;
        } else if (!current.content.includes(prompt)) {
          current.content = `${current.content.trim()}\n\n${prompt}`;
        }
      }
      status.value =
        kind === "confirm" ? "等待确认…" : "等待你的回复…";
      current.streaming = false;
      return;
    }

    if (event === "run_complete" || event === "run_result") {
      const content = String(data.content || "");
      if (content) current.content = content;
      const ok = data.ok !== false;
      const err = String(data.error || "");
      if (!ok && err) {
        current.error = true;
        if (!current.content) current.content = err;
      }
      const statusRaw = String(data.status || "").trim();
      // interactive 挂起时 status 常为 awaiting_*；pending 已由 awaiting_user 设置
      if (
        statusRaw &&
        !statusRaw.startsWith("awaiting") &&
        statusRaw !== "paused"
      ) {
        // 正常收工则清挂起
        if (ok) pendingAwait.value = null;
      }
      current.streaming = false;
      return;
    }

    if (event === "error") {
      if (!data.recoverable) {
        current.error = true;
        current.content =
          current.content || String(data.error || "未知错误");
        current.streaming = false;
        pendingAwait.value = null;
      }
      return;
    }

    if (event === "run_finished") {
      current.streaming = false;
      agentPhase.value = null;
      if (!pendingAwait.value) {
        status.value = current.error ? "出错" : "就绪";
      }
    }
  }

  async function consumeStream(
    res: Response,
    current: ChatMessage,
  ): Promise<void> {
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => "");
      current.error = true;
      current.content = text || `HTTP ${res.status}`;
      current.streaming = false;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseChunk(buffer);
      buffer = parsed.rest;
      for (const ev of parsed.events) {
        applySseEvent(ev.event, ev.data, current);
        messages.value = [...messages.value];
      }
    }
    if (buffer.trim()) {
      const parsed = parseSseChunk(buffer + "\n\n");
      for (const ev of parsed.events) {
        applySseEvent(ev.event, ev.data, current);
      }
    }
    current.streaming = false;
    messages.value = [...messages.value];
  }

  async function send(text: string) {
    const content = text.trim();
    if (!content || !ready.value || busy.value) return;

    persist();
    busy.value = true;
    agentPhase.value = "deciding";

    const pending = pendingAwait.value;
    const isResume = Boolean(pending);

    messages.value.push({
      id: uuid(),
      role: "user",
      content,
    });

    const assistant: ChatMessage = {
      id: uuid(),
      role: "assistant",
      content: "",
      streaming: true,
    };
    messages.value.push(assistant);

    // resume 前清掉挂起，避免重复；若失败再靠事件恢复
    if (isResume) pendingAwait.value = null;

    try {
      const key = normalizeSessionKey(sessionId.value);
      const url = isResume ? "/v1/chat/resume" : "/v1/chat";
      const body = isResume
        ? {
            session_id: key,
            user_reply: content,
            run_id: pending?.runId || undefined,
            await_token: pending?.awaitToken || undefined,
            stream: true,
          }
        : {
            session_id: key,
            message: content,
            stream: true,
            wait_profile: WAIT_PROFILE,
          };

      status.value = isResume ? "继续处理…" : "处理中…";
      const res = await fetch(url, {
        method: "POST",
        headers: buildHeaders(),
        body: JSON.stringify(body),
      });
      await consumeStream(res, assistant);
    } catch (err) {
      assistant.error = true;
      assistant.content =
        err instanceof Error ? err.message : "请求失败";
      assistant.streaming = false;
      status.value = "出错";
    } finally {
      busy.value = false;
      agentPhase.value = null;
      if (!pendingAwait.value && !assistant.error) {
        status.value = "就绪";
      }
      messages.value = [...messages.value];
    }
  }

  return {
    token,
    sessionId,
    messages,
    busy,
    status,
    agentPhase,
    showTools,
    includeThought,
    mcpReady,
    mcpDetail,
    pendingAwait,
    awaitingUser,
    ready,
    persist,
    newSession,
    refreshMcpStatus,
    loadHistory,
    send,
  };
}
