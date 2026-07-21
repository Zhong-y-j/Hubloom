<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useChat } from "@/composables/useChat";
import { renderMarkdownToHtml } from "@/utils/markdown";
import ChatA2uiBlock from "@/components/ChatA2uiBlock.vue";
import { formatA2uiActionAsChat } from "@/utils/a2uiAction";
import type { A2uiClientAction } from "@/utils/a2uiAction";

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

const phaseLabel = computed(() => {
  if (agentPhase.value === "understanding") return "理解中";
  if (agentPhase.value === "thinking") return "思考中";
  if (agentPhase.value === "replying") return "回复中";
  return "";
});

/** 纯 A2UI 落库时的占位正文，有界面时不重复展示 */
function isA2uiPlaceholder(content: string): boolean {
  return content.trim() === "（交互界面）";
}

function onCredChange() {
  persist();
  status.value = ready.value ? "就绪" : "请填写 Token 与用户 ID";
}

async function scrollBottom() {
  await nextTick();
  const el = listRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

/** 思考过程默认停在最新；流式时持续跟随，历史消息首次展示也滚到底 */
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

watch(messages, () => {
  void scrollBottom();
  void scrollThoughtToLatest();
}, { deep: true });

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

/** 从工具 body JSON 解析 MCP 的 tag / 业务 tool_name（兼容 call 的 args 与返回里的 tool 字段） */
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

/**
 * 标题旁展示的 tag / 业务工具名。
 * 返回/失败卡片常没有 tag，向前找同名「调用」卡片补全。
 */
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
  <div class="chat-layout">
    <aside class="chat-sidebar">
      <div class="chat-brand">
        <div class="chat-brand-mark">A</div>
        <div>
          <h2>Agent 对话</h2>
          <p>接 HubloomAgent · SSE</p>
        </div>
      </div>

      <p class="chat-intro">
        与 <code>examples/chat</code> 同源：前端只传 Token + 用户 ID。最终回复的
        Markdown 流式展示；A2UI 由后端 <code>event: a2ui</code> 按消息增量下发并渐进渲染。
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
          <button type="button" class="btn primary block" @click="loadHistory">
            加载历史
          </button>
          <button type="button" class="btn ghost" @click="newSession">
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
            <option value="markdown">Markdown（纯文本）</option>
            <option value="a2ui">A2UI（表单 / 列表）</option>
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

    <section class="chat-main">
      <header class="chat-top">
        <h2>对话</h2>
        <span v-if="route" class="badge">{{
          route === "thought" ? "深度思考" : route === "chat" ? "快答" : route
        }}</span>
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
            :class="{ error: m.error }"
          >
            <div
              v-if="
                m.streaming &&
                agentPhase &&
                !m.content &&
                !m.a2uiMessages?.length &&
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

            <!-- Think 已结束、Respond 尚未出字：在结果区给明确过渡，避免像卡住 -->
            <div
              v-if="
                m.streaming &&
                agentPhase === 'replying' &&
                !m.content &&
                !m.a2uiMessages?.length
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
              v-if="m.content && !(m.a2uiMessages?.length && isA2uiPlaceholder(m.content))"
              class="answer-body"
              :class="{
                'markdown-body': true,
                typing: m.streaming,
              }"
              v-html="renderMarkdownToHtml(m.content)"
            />

            <ChatA2uiBlock
              v-if="m.a2uiMessages?.length"
              :messages="m.a2uiMessages"
              :reload-key="m.a2uiReloadKey || 0"
              :disabled="busy"
              @action="onA2uiAction"
            />
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
  </div>
</template>
