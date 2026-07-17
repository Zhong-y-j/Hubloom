<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { SCENARIOS, getScenario } from "@/data/scenarios";
import type { Scenario, A2uiMessage } from "@/types/a2ui";
import { useA2uiSurface } from "@/composables/useA2uiSurface";
import {
  parsePastedA2ui,
  PASTE_DEMO_FULL,
} from "@/utils/parsePastedA2ui";
import A2uiSurfaceHost from "@/components/A2uiSurfaceHost.vue";

type LabSource = "preset" | "paste";

const scenarioList = SCENARIOS;
const current = ref<Scenario | null>(null);
const source = ref<LabSource>("preset");
const pasteText = ref("");
const pasteError = ref("");
const pasteHint = ref("");
const pastedMessages = ref<A2uiMessage[] | null>(null);
const { surface, lastAction, loadMessages, clear } = useA2uiSurface();

const jsonText = computed(() => {
  if (source.value === "paste") {
    return pastedMessages.value
      ? JSON.stringify(pastedMessages.value, null, 2)
      : "粘贴 JSON 后点「渲染」";
  }
  return current.value
    ? JSON.stringify(current.value.messages, null, 2)
    : "请选择场景";
});

function selectScenario(id: string) {
  source.value = "preset";
  pasteError.value = "";
  pasteHint.value = "";
  pastedMessages.value = null;
  clear();
  const s = getScenario(id);
  if (!s) return;
  current.value = s;
  loadMessages(s.messages);
}

function switchToPaste() {
  source.value = "paste";
  current.value = null;
  pasteError.value = "";
  pasteHint.value = "";
  clear();
}

function renderPaste() {
  pasteError.value = "";
  pasteHint.value = "";
  const { messages, error, hint } = parsePastedA2ui(pasteText.value);
  if (error) {
    pasteError.value = error;
    pastedMessages.value = null;
    clear();
    return;
  }
  pastedMessages.value = messages;
  if (hint) pasteHint.value = hint;
  loadMessages(messages);
}

function fillDemoAndRender() {
  pasteText.value = PASTE_DEMO_FULL.trim();
  renderPaste();
}

async function copyJson() {
  await navigator.clipboard.writeText(jsonText.value);
}

onMounted(() => {
  if (scenarioList.length) {
    selectScenario(scenarioList[0].id);
  }
});
</script>

<template>
  <div class="lab">
    <header class="hero">
      <p class="eyebrow">A2UI 场景实验室</p>
      <h1>组件与 JSON 对照</h1>
      <p class="lead">
        预设场景，或粘贴 Agent / 官网学习脚本产出的 A2UI JSON（单条、数组、或含
        <code>&lt;a2ui-json&gt;</code> 的原文）。真实对话请切到「Agent 对话」。
      </p>
      <div class="tabs" role="tablist">
        <button
          v-for="item in scenarioList"
          :key="item.id"
          type="button"
          :class="{ active: source === 'preset' && current?.id === item.id }"
          @click="selectScenario(item.id)"
        >
          {{ item.title }}
        </button>
        <button
          type="button"
          :class="{ active: source === 'paste' }"
          @click="switchToPaste"
        >
          粘贴渲染
        </button>
      </div>
    </header>

    <section v-if="source === 'preset' && current" class="meta">
      <div class="bubble user">
        <span>用户</span>
        <p>{{ current.userSays }}</p>
      </div>
      <div class="bubble agent">
        <span>Agent 文本</span>
        <p>{{ current.agentSays }}</p>
      </div>
      <p class="why">{{ current.why }}</p>
    </section>

    <section v-else-if="source === 'paste'" class="meta paste-meta">
      <p class="why">
        列表要能显示，必须同时有
        <code>updateComponents</code> +
        <code>updateDataModel</code>（填
        <code>/items</code>）。只贴组件、不贴数据时右侧会是空白。
      </p>
      <textarea
        v-model="pasteText"
        class="paste-input"
        rows="12"
        spellcheck="false"
        placeholder="粘贴完整 LLM 输出（推荐含 3 个 a2ui-json），或消息数组"
      />
      <div class="paste-actions">
        <button type="button" class="btn primary" @click="renderPaste">
          渲染
        </button>
        <button type="button" class="ghost" @click="fillDemoAndRender">
          填入完整示例
        </button>
        <button
          type="button"
          class="ghost"
          @click="
            pasteText = '';
            pasteError = '';
            pasteHint = '';
            pastedMessages = null;
            clear();
          "
        >
          清空
        </button>
      </div>
      <p v-if="pasteError" class="paste-error">{{ pasteError }}</p>
      <p v-else-if="pasteHint" class="paste-hint">{{ pasteHint }}</p>
    </section>

    <main class="split">
      <section class="panel">
        <header class="panel-head">
          <h2>{{ source === "paste" ? "解析后的消息" : "TS 中的 A2UI JSON" }}</h2>
          <button type="button" class="ghost" @click="copyJson">复制</button>
        </header>
        <pre class="json-view">{{ jsonText }}</pre>
      </section>

      <section class="panel">
        <header class="panel-head">
          <h2>官方 Catalog 渲染</h2>
          <span class="hint">看组件如何由 JSON 长成 UI</span>
        </header>
        <div class="render-host a2ui-theme">
          <A2uiSurfaceHost v-if="surface" :surface="surface" />
          <p v-else class="placeholder">
            {{ source === "paste" ? "粘贴后点击「渲染」" : "选择场景后渲染" }}
          </p>
        </div>
        <div v-if="lastAction" class="action-log">
          <h3>用户 action 回传</h3>
          <pre>{{ JSON.stringify(lastAction, null, 2) }}</pre>
        </div>
      </section>
    </main>
  </div>
</template>
