<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { SCENARIOS, getScenario } from "@/data/scenarios";
import type { Scenario } from "@/types/a2ui";
import { useA2uiSurface } from "@/composables/useA2uiSurface";
import A2uiSurfaceHost from "@/components/A2uiSurfaceHost.vue";

const scenarioList = SCENARIOS;
const current = ref<Scenario | null>(null);
const { surface, lastAction, loadMessages, clear } = useA2uiSurface();

const jsonText = computed(() =>
  current.value
    ? JSON.stringify(current.value.messages, null, 2)
    : "请选择场景"
);

function selectScenario(id: string) {
  clear();
  const s = getScenario(id);
  if (!s) return;
  current.value = s;
  loadMessages(s.messages);
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
        本地写死场景，不经 Agent。用来对比 Markdown / 结构化组件 / Catalog。
        真实对话请切到「Agent 对话」。
      </p>
      <div class="tabs" role="tablist">
        <button
          v-for="item in scenarioList"
          :key="item.id"
          type="button"
          :class="{ active: current?.id === item.id }"
          @click="selectScenario(item.id)"
        >
          {{ item.title }}
        </button>
      </div>
    </header>

    <section v-if="current" class="meta">
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

    <main class="split">
      <section class="panel">
        <header class="panel-head">
          <h2>TS 中的 A2UI JSON</h2>
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
          <p v-else class="placeholder">选择场景后渲染</p>
        </div>
        <div v-if="lastAction" class="action-log">
          <h3>用户 action 回传</h3>
          <pre>{{ JSON.stringify(lastAction, null, 2) }}</pre>
        </div>
      </section>
    </main>
  </div>
</template>
