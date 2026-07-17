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

function onCredChange() {
  persist();
  status.value = ready.value ? "就绪" : "请填写 Token 与用户 ID";
}

async function scrollBottom() {
  await nextTick();
  const el = listRef.value;
  if (el) el.scrollTop = el.scrollHeight;
}

watch(messages, () => scrollBottom(), { deep: true });

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
        Markdown 流式展示；若有 A2UI，由后端 <code>event: a2ui</code> 下发并在此渲染。
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
                !m.a2uiMessages?.length
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
              <div v-if="m.thought" class="thought-body">{{ m.thought }}</div>
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
                  </summary>
                  <pre>{{ t.body }}</pre>
                </details>
              </div>
            </details>

            <div
              v-if="m.content"
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
