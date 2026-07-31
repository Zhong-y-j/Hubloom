<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useChat } from "@/composables/useChat";
import { renderMarkdownToHtml } from "@/utils/markdown";
import type { ChatMessage } from "@/types/chat";

const {
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
  awaitingUser,
  pendingAwait,
  ready,
  persist,
  newSession,
  refreshMcpStatus,
  loadHistory,
  send,
} = useChat();

const draft = ref("");
const listRef = ref<HTMLElement | null>(null);

const phaseLabel = computed(() => {
  if (agentPhase.value === "deciding") return "决策中";
  if (agentPhase.value === "acting") return "执行中";
  if (agentPhase.value === "replying") return "回复中";
  return "";
});

/** 仅最新一条助手消息默认展开思考；历史回复折叠 */
const latestAssistantId = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === "assistant") return messages.value[i].id;
  }
  return null;
});

function isThoughtOpen(m: ChatMessage): boolean {
  return m.id === latestAssistantId.value;
}

function onCredChange() {
  persist();
  status.value = ready.value ? "就绪" : "请填写用户 ID";
}

function onNewSession() {
  newSession();
}

async function onLoadHistory() {
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
  const id = latestAssistantId.value;
  if (!root || !id) return;
  const m = messages.value.find((x) => x.id === id);
  if (!m?.thought) return;
  const el = root.querySelector(
    `[data-thought-scroll="${CSS.escape(id)}"]`,
  );
  if (!(el instanceof HTMLElement)) return;
  if (m.streaming || !el.dataset.scrolledOnce) {
    el.scrollTop = el.scrollHeight;
    if (!m.streaming) el.dataset.scrolledOnce = "1";
  }
}

watch(
  messages,
  () => {
    void scrollBottom();
    void scrollThoughtToLatest();
  },
  { deep: true },
);

async function onSubmit() {
  const text = draft.value;
  draft.value = "";
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
  const needFallback = !own.tag || (gateway === "call_api" && !own.apiTool);
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

function showPhaseOnly(m: ChatMessage): boolean {
  return Boolean(
    m.streaming &&
      agentPhase.value &&
      !m.content.trim() &&
      !(m.thought || (showTools.value && m.tools?.length)),
  );
}

onMounted(async () => {
  onCredChange();
  await refreshMcpStatus();
  if (ready.value) await loadHistory();
});
</script>

<template>
  <div class="chat-layout">
    <aside class="chat-sidebar">
      <div class="chat-brand">
        <div class="chat-brand-mark" aria-hidden="true">H</div>
        <div class="chat-brand-text">
          <p class="chat-brand-name">Hubloom</p>
          <h2>Agent 对话</h2>
        </div>
      </div>

      <p class="chat-intro">
        对接 Hubloom Serve。Markdown 回复；需要补充信息时在输入框直接回答即可（interactive 挂起续跑）。
      </p>

      <div class="config-card">
        <p class="config-card-title">凭证</p>
        <label class="field">
          <span>业务 Token（可选）</span>
          <input
            v-model="token"
            type="password"
            autocomplete="off"
            placeholder="需鉴权时填写；无鉴权可留空"
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
        <label class="checkbox">
          <input v-model="showTools" type="checkbox" />
          显示工具调用
        </label>
        <label class="checkbox">
          <input
            v-model="includeThought"
            type="checkbox"
            @change="persist"
          />
          历史填回思考
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
          <h2>业务会话</h2>
          <span v-if="awaitingUser" class="badge badge-await">等待回复</span>
        </header>

        <div class="chat-main-body">
          <div ref="listRef" class="chat-messages">
            <div
              v-if="!messages.length"
              class="empty-state"
              :class="ready ? 'empty-state-ready' : 'empty-state-disconnected'"
            >
              <template v-if="ready">
                <p class="empty-title">开始办事</p>
                <p class="empty-desc">
                  用自然语言查询或办理已接入的业务。缺参时 Agent
                  会追问，你在下方输入框回复即可继续同一轮。
                </p>
                <p class="empty-examples-label">可以试试</p>
                <ul class="empty-examples">
                  <li>你能做什么？</li>
                  <li>列出当前有哪些资源</li>
                  <li>帮我新建一条记录</li>
                </ul>
              </template>
              <template v-else>
                <p class="empty-title">请填写用户 ID</p>
                <p class="empty-desc">
                  在左侧填写用户 ID 后即可开始。业务 Token
                  仅在接口需要鉴权时填写，可留空。
                </p>
              </template>
            </div>

            <template v-for="m in messages" :key="m.id">
              <div
                v-if="m.role === 'user'"
                class="msg user"
                :class="{ 'msg-event': m.source === 'event' }"
              >
                <span v-if="m.source === 'event'" class="event-tag">事件</span>
                {{ m.content }}
              </div>
              <div
                v-else
                class="msg assistant turn"
                :class="{ error: m.error }"
              >
                <div
                  v-if="showPhaseOnly(m)"
                  class="agent-status"
                  :data-state="agentPhase || 'deciding'"
                >
                  <span class="agent-status-label">{{ phaseLabel }}</span>
                  <span class="agent-status-dots">
                    <span class="dot" /><span class="dot" /><span class="dot" />
                  </span>
                </div>

                <details
                  v-if="m.thought || (showTools && m.tools?.length)"
                  class="thought-panel"
                  :open="isThoughtOpen(m)"
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
                  >
                    {{ m.thought }}
                  </div>
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
                        <span class="tool-card-name">{{
                          toolName(t.title)
                        }}</span>
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
                            <span class="tool-target-api">{{
                              meta.apiTool
                            }}</span>
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
                    agentPhase === 'replying' &&
                    !m.content.trim()
                  "
                  class="answer-pending"
                >
                  <span class="answer-pending-bar" aria-hidden="true" />
                  <div class="answer-pending-copy">
                    <strong>正在生成回复</strong>
                    <span>思考已完成，正在输出最终答案…</span>
                  </div>
                  <span class="agent-status-dots answer-pending-dots">
                    <span class="dot" /><span class="dot" /><span class="dot" />
                  </span>
                </div>

                <div
                  v-if="m.content"
                  class="answer-body markdown-body"
                  :class="{
                    typing: m.streaming,
                    'await-prompt': m.awaitPrompt,
                  }"
                  v-html="renderMarkdownToHtml(m.content)"
                />
              </div>
            </template>
          </div>

          <div v-if="awaitingUser && pendingAwait" class="await-banner">
            <strong>{{
              pendingAwait.kind === "confirm" ? "请确认" : "请补充信息"
            }}</strong>
            <span>{{ pendingAwait.prompt || "在下方输入框回复以继续。" }}</span>
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
                  !ready
                    ? '请先填写用户 ID'
                    : awaitingUser
                      ? '输入回复以继续本轮…'
                      : '输入消息，Enter 发送，Shift+Enter 换行'
                "
                @keydown="onKeydown"
              />
              <button
                type="submit"
                class="btn primary"
                :disabled="!ready || busy || !draft.trim()"
              >
                {{ awaitingUser ? "继续" : "发送" }}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  </div>
</template>
