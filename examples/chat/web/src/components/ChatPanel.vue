<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useChat } from "@/composables/useChat";
import { renderMarkdownToHtml } from "@/utils/markdown";
import ChatA2uiBlock from "@/components/ChatA2uiBlock.vue";
import { formatA2uiActionAsChat } from "@/utils/a2uiAction";
import type { A2uiClientAction } from "@/utils/a2uiAction";
import type { AnswerPart, ChatMessage } from "@/types/chat";

const {
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
} = useChat();

const draft = ref("");
const listRef = ref<HTMLElement | null>(null);
const panelMessageId = ref<string | null>(null);
const panelOpen = ref(false);
const autoOpenedForId = ref<string | null>(null);

const phaseLabel = computed(() => {
  if (agentPhase.value === "understanding") return "理解中";
  if (agentPhase.value === "thinking") return "思考中";
  if (agentPhase.value === "presenting") return "呈现决策中";
  if (agentPhase.value === "replying") return "回复中";
  return "";
});

const panelMessage = computed(() => {
  const id = panelMessageId.value;
  if (!id) return null;
  return messages.value.find((m) => m.id === id) || null;
});

function messageHasA2ui(m: ChatMessage): boolean {
  return Boolean(
    m.a2uiMessages?.length ||
      m.a2uiProse?.trim() ||
      m.answerParts?.some(
        (p) => p.type === "a2ui" || (p.type === "text" && p.channel === "a2ui"),
      ),
  );
}

const panelHasA2ui = computed(() => {
  const m = panelMessage.value;
  return m ? messageHasA2ui(m) : false;
});

function isA2uiPlaceholder(content: string): boolean {
  return content.trim() === "（交互界面）";
}

function visibleAnswerText(content: string): string {
  const raw = (content || "").trim();
  if (!raw) return "";
  if (isA2uiPlaceholder(raw)) return "";
  if (!raw.includes("<a2ui-json>")) return raw;
  return raw
    .replace(/<a2ui-json>[\s\S]*?<\/a2ui-json>/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** 气泡：仅 Markdown 通道 */
function answerMarkdown(m: ChatMessage): string {
  if (m.answerParts?.length) {
    const joined = m.answerParts
      .filter(
        (p): p is { type: "text"; text: string; channel?: "markdown" | "a2ui" } =>
          p.type === "text" && (p.channel || "markdown") === "markdown",
      )
      .map((p) => p.text)
      .join("\n\n");
    return visibleAnswerText(joined);
  }
  return visibleAnswerText(m.content);
}

/** 右侧：A2UI 通道全文（文案 + 表单） */
function a2uiPanelParts(m: ChatMessage): AnswerPart[] {
  if (m.answerParts?.length) {
    const parts = m.answerParts.filter(
      (p) =>
        p.type === "a2ui" || (p.type === "text" && p.channel === "a2ui"),
    );
    if (parts.length) return parts;
  }
  const fallback: AnswerPart[] = [];
  if (m.a2uiProse?.trim()) {
    fallback.push({ type: "text", text: m.a2uiProse.trim(), channel: "a2ui" });
  }
  if (m.a2uiMessages?.length) fallback.push({ type: "a2ui" });
  return fallback;
}

function openA2uiPanel(messageId: string) {
  panelMessageId.value = messageId;
  panelOpen.value = true;
}

function closeA2uiPanel() {
  panelOpen.value = false;
}

function toggleA2uiPanel(messageId: string) {
  if (panelOpen.value && panelMessageId.value === messageId) {
    closeA2uiPanel();
    return;
  }
  openA2uiPanel(messageId);
}

function onCredChange() {
  persist();
  status.value = ready.value ? "就绪" : "请填写 Token 与用户 ID";
}

function onNewSession() {
  closeA2uiPanel();
  panelMessageId.value = null;
  autoOpenedForId.value = null;
  newSession();
}

async function onLoadHistory() {
  closeA2uiPanel();
  panelMessageId.value = null;
  autoOpenedForId.value = null;
  await loadHistory();
}

async function scrollBottom() {
  await nextTick();
  const el = listRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

async function scrollThoughtToLatest() {
  await nextTick();
  const root = listRef.value;
  if (!root) return;
  for (const m of messages.value) {
    if (m.role !== "assistant" || !m.thought) continue;
    const el = root.querySelector(
      `[data-thought-scroll="${CSS.escape(m.id)}"]`,
    );
    if (!(el instanceof HTMLElement)) continue;
    if (m.streaming || !el.dataset.scrolledOnce) {
      el.scrollTop = el.scrollHeight;
      if (!m.streaming) el.dataset.scrolledOnce = "1";
    }
  }
}

watch(
  messages,
  () => {
    void scrollBottom();
    void scrollThoughtToLatest();
    const streaming = [...messages.value]
      .reverse()
      .find(
        (m) => m.role === "assistant" && m.streaming && messageHasA2ui(m),
      );
    if (streaming && autoOpenedForId.value !== streaming.id) {
      autoOpenedForId.value = streaming.id;
      openA2uiPanel(streaming.id);
    }
  },
  { deep: true },
);

async function onSubmit() {
  const text = draft.value;
  draft.value = "";
  await send(text);
}

async function onA2uiAction(action: A2uiClientAction) {
  const text = formatA2uiActionAsChat(action);
  await send(text);
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void onSubmit();
  }
}

function toolKind(title: string): "call" | "ret" | "fail" | "" {
  const t = title.trim();
  if (t.startsWith("调用")) return "call";
  if (t.startsWith("返回")) return "ret";
  if (t.startsWith("失败")) return "fail";
  return "";
}

function toolKindLabel(title: string): string {
  const k = toolKind(title);
  if (k === "call") return "调用";
  if (k === "ret") return "返回";
  if (k === "fail") return "失败";
  return "";
}

function toolName(title: string): string {
  return title
    .replace(/^调用\s*·\s*/, "")
    .replace(/^返回\s*·\s*/, "")
    .replace(/^失败\s*·\s*/, "")
    .trim();
}

function parseToolTarget(body: string): { tag?: string; apiTool?: string } {
  const raw = (body || "").trim();
  if (!raw.startsWith("{") && !raw.startsWith("[")) return {};
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (!data || typeof data !== "object" || Array.isArray(data)) return {};
    const tag = typeof data.tag === "string" ? data.tag.trim() : "";
    const apiTool =
      (typeof data.tool_name === "string" && data.tool_name.trim()) ||
      (typeof data.tool === "string" && data.tool.trim()) ||
      "";
    return {
      ...(tag ? { tag } : {}),
      ...(apiTool ? { apiTool } : {}),
    };
  } catch {
    return {};
  }
}

function toolTargetMeta(
  tools: { title: string; body: string }[],
  index: number,
): { tag?: string; apiTool?: string } {
  const current = tools[index];
  if (!current) return {};
  const own = parseToolTarget(current.body);
  const gateway = toolName(current.title);

  let fromCall: { tag?: string; apiTool?: string } = {};
  const needFallback =
    !own.tag || (gateway === "call_tool" && !own.apiTool);
  if (needFallback) {
    for (let i = index - 1; i >= 0; i--) {
      const prev = tools[i];
      if (!prev || toolKind(prev.title) !== "call") continue;
      if (toolName(prev.title) !== gateway) continue;
      fromCall = parseToolTarget(prev.body);
      break;
    }
  }
  return {
    tag: own.tag || fromCall.tag,
    apiTool: own.apiTool || fromCall.apiTool,
  };
}

onMounted(async () => {
  onCredChange();
  await refreshMcpStatus();
  if (ready.value) await loadHistory();
});
</script>

<template>
  <div
    class="chat-layout"
    :class="{ 'chat-layout-panel-open': panelOpen && panelHasA2ui }"
  >
    <aside class="chat-sidebar">
      <div class="chat-brand">
        <div class="chat-brand-mark">A</div>
        <div>
          <h2>Agent 对话</h2>
          <p>接 HubloomAgent · SSE</p>
        </div>
      </div>

      <p class="chat-intro">
        气泡展示 Markdown；交互在右侧面板。推荐
        <strong>Auto</strong>：Think → Present → Respond（按需并行 A2UI）。
      </p>

      <div class="config-card">
        <p class="config-card-title">凭证</p>
        <label class="field">
          <span>业务 Token</span>
          <input
            v-model="token"
            type="password"
            autocomplete="off"
            placeholder="X-MCP-Token"
            @change="onCredChange"
          />
        </label>
        <label class="field">
          <span>用户 ID</span>
          <input
            v-model="sessionId"
            type="text"
            autocomplete="off"
            placeholder="web-…"
            @change="onCredChange"
          />
        </label>
        <div class="chat-actions">
          <button type="button" class="btn primary block" @click="onLoadHistory">
            加载历史
          </button>
          <button type="button" class="btn ghost" @click="onNewSession">
            新会话
          </button>
        </div>
      </div>

      <div class="config-card config-card-compact">
        <p class="config-card-title">服务端</p>
        <div
          class="pill"
          :data-state="
            mcpReady === null ? 'loading' : mcpReady ? 'ok' : 'error'
          "
        >
          <span class="dot" />
          <span class="pill-text">{{
            mcpReady === null
              ? "检查 MCP…"
              : mcpReady
                ? "MCP 就绪"
                : "MCP 未就绪"
          }}</span>
        </div>
        <p class="connect-detail">{{ mcpDetail }}</p>
        <label class="field">
          <span>呈现模式</span>
          <select v-model="presentMode" @change="persist">
            <option value="auto">Auto（Markdown + 按需 A2UI）</option>
            <option value="markdown">Markdown（纯文本）</option>
            <option value="a2ui">A2UI（仅交互界面）</option>
          </select>
        </label>
        <label class="checkbox">
          <input v-model="showTools" type="checkbox" />
          显示工具调用
        </label>
        <button type="button" class="btn ghost" @click="refreshMcpStatus">
          刷新状态
        </button>
      </div>

      <p class="chat-status">{{ status }}</p>
    </aside>

    <div class="chat-workspace">
      <section class="chat-main">
        <header class="chat-top">
          <h2>对话</h2>
          <span v-if="route" class="badge">{{
            route === "thought"
              ? "深度思考"
              : route === "chat"
                ? "快答"
                : route === "auto"
                  ? "Auto"
                  : route === "present"
                    ? "Present"
                    : route
          }}</span>
          <button
            v-if="panelHasA2ui && !panelOpen"
            type="button"
            class="btn ghost chat-top-panel-btn"
            @click="panelOpen = true"
          >
            打开交互面板
          </button>
        </header>

        <div ref="listRef" class="chat-messages">
          <div
            v-if="!messages.length"
            class="empty-state"
            :class="ready ? 'empty-state-ready' : 'empty-state-disconnected'"
          >
            <p class="empty-title">{{ ready ? "开始对话" : "请填写凭证" }}</p>
            <p class="empty-desc">
              {{
                ready
                  ? "用自然语言查询、操作已接入的 API。"
                  : "在左侧填写业务 Token 与用户 ID 后即可开始。"
              }}
            </p>
          </div>

          <template v-for="m in messages" :key="m.id">
            <div v-if="m.role === 'user'" class="msg user">{{ m.content }}</div>
            <div
              v-else
              class="msg assistant turn"
              :class="{
                error: m.error,
                'turn-panel-active':
                  panelOpen && panelMessageId === m.id && messageHasA2ui(m),
              }"
            >
              <div
                v-if="
                  m.streaming &&
                  agentPhase &&
                  !answerMarkdown(m) &&
                  !messageHasA2ui(m) &&
                  !(m.thought || (showTools && m.tools?.length))
                "
                class="agent-status"
                :data-state="agentPhase"
              >
                <span class="agent-status-label">{{ phaseLabel }}</span>
                <span class="agent-status-dots">
                  <span class="dot" /><span class="dot" /><span class="dot" />
                </span>
              </div>

              <details
                v-if="m.thought || (showTools && m.tools?.length)"
                class="thought-panel"
                open
              >
                <summary class="thought-summary">
                  {{
                    m.thought?.trim()
                      ? `思考过程（${m.thought.trim().length} 字）`
                      : "思考过程"
                  }}
                </summary>
                <div
                  v-if="m.thought"
                  class="thought-body"
                  :data-thought-scroll="m.id"
                >{{ m.thought }}</div>
                <div
                  v-if="showTools && m.tools?.length"
                  class="thought-tools"
                >
                  <details
                    v-for="(t, i) in m.tools"
                    :key="i"
                    class="tool-card"
                  >
                    <summary class="tool-card-summary">
                      <span
                        v-if="toolKind(t.title)"
                        class="tool-chip"
                        :class="toolKind(t.title)"
                      >{{ toolKindLabel(t.title) }}</span>
                      <span class="tool-card-name">{{ toolName(t.title) }}</span>
                      <template
                        v-for="meta in [toolTargetMeta(m.tools || [], i)]"
                        :key="'target'"
                      >
                        <template v-if="meta.tag">
                          <span class="tool-sep">·</span>
                          <span class="tool-target-tag">{{ meta.tag }}</span>
                        </template>
                        <template v-if="meta.apiTool">
                          <span class="tool-sep">/</span>
                          <span class="tool-target-api">{{ meta.apiTool }}</span>
                        </template>
                      </template>
                    </summary>
                    <pre>{{ t.body }}</pre>
                  </details>
                </div>
              </details>

              <div
                v-if="
                  m.streaming &&
                  (agentPhase === 'presenting' || agentPhase === 'replying') &&
                  !answerMarkdown(m) &&
                  !messageHasA2ui(m)
                "
                class="answer-pending"
              >
                <span class="answer-pending-bar" aria-hidden="true" />
                <div class="answer-pending-copy">
                  <strong>{{
                    agentPhase === "presenting"
                      ? "正在决定呈现方式"
                      : "正在生成回复"
                  }}</strong>
                  <span>{{
                    agentPhase === "presenting"
                      ? "思考已完成，Present 判定是否需要交互面板…"
                      : "思考已完成，正在输出最终答案…"
                  }}</span>
                </div>
                <span class="agent-status-dots answer-pending-dots">
                  <span class="dot" /><span class="dot" /><span class="dot" />
                </span>
              </div>

              <div
                v-if="answerMarkdown(m)"
                class="answer-body markdown-body"
                :class="{ typing: m.streaming }"
                v-html="renderMarkdownToHtml(answerMarkdown(m))"
              />

              <button
                v-if="messageHasA2ui(m)"
                type="button"
                class="a2ui-panel-chip"
                :class="{ active: panelOpen && panelMessageId === m.id }"
                @click="toggleA2uiPanel(m.id)"
              >
                <span class="a2ui-panel-chip-dot" aria-hidden="true" />
                <span>{{
                  panelOpen && panelMessageId === m.id
                    ? "交互面板已打开"
                    : "打开交互面板"
                }}</span>
              </button>
            </div>
          </template>
        </div>

        <form
          class="composer"
          :class="{ 'composer-disabled': !ready }"
          @submit.prevent="onSubmit"
        >
          <div class="composer-inner">
            <textarea
              v-model="draft"
              rows="2"
              :disabled="!ready || busy"
              :placeholder="
                ready
                  ? '输入消息，Enter 发送，Shift+Enter 换行'
                  : '请先填写 Token 与用户 ID'
              "
              @keydown="onKeydown"
            />
            <button
              type="submit"
              class="btn primary"
              :disabled="!ready || busy || !draft.trim()"
            >
              发送
            </button>
          </div>
        </form>
      </section>

      <aside
        v-if="panelOpen && panelHasA2ui && panelMessage"
        class="a2ui-drawer"
        aria-label="交互面板"
      >
        <header class="a2ui-drawer-top">
          <div>
            <p class="a2ui-drawer-kicker">交互面板</p>
            <h3>A2UI</h3>
          </div>
          <button
            type="button"
            class="btn ghost a2ui-drawer-close"
            aria-label="关闭交互面板"
            @click="closeA2uiPanel"
          >
            关闭
          </button>
        </header>
        <div class="a2ui-drawer-body">
          <template v-for="(part, pi) in a2uiPanelParts(panelMessage)" :key="pi">
            <div
              v-if="part.type === 'text' && visibleAnswerText(part.text)"
              class="a2ui-drawer-prose markdown-body"
              v-html="renderMarkdownToHtml(visibleAnswerText(part.text))"
            />
            <ChatA2uiBlock
              v-else-if="part.type === 'a2ui' && panelMessage.a2uiMessages?.length"
              :messages="panelMessage.a2uiMessages || []"
              :reload-key="panelMessage.a2uiReloadKey || 0"
              :disabled="busy"
              @action="onA2uiAction"
            />
          </template>
        </div>
      </aside>
    </div>
  </div>
</template>
