<script setup lang="ts">
/**
 * 单条助手消息内的 A2UI 渲染块。
 * 每条消息独立 MessageProcessor，避免多气泡互相覆盖 surface。
 */
import { onBeforeUnmount, ref, watch } from "vue";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { basicCatalog } from "@a2ui/lit/v0_9";
import type { A2uiMessage } from "@/types/a2ui";
import A2uiSurfaceHost from "@/components/A2uiSurfaceHost.vue";

const props = defineProps<{
  messages: A2uiMessage[];
}>();

const surface = ref<unknown | null>(null);
const lastAction = ref<unknown | null>(null);
const errorText = ref("");

let processor: MessageProcessor | null = null;

function patchCatalog(messages: A2uiMessage[]): A2uiMessage[] {
  return messages.map((m) => {
    if ("createSurface" in m && m.createSurface) {
      return {
        ...m,
        createSurface: {
          ...m.createSurface,
          catalogId: basicCatalog.id,
        },
      };
    }
    return m;
  });
}

function load(messages: A2uiMessage[]) {
  processor = null;
  surface.value = null;
  lastAction.value = null;
  errorText.value = "";
  if (!messages?.length) return;

  const mp = new MessageProcessor([basicCatalog], (action: unknown) => {
    lastAction.value = action;
  });
  processor = mp;
  mp.onSurfaceCreated((s: unknown) => {
    surface.value = s;
  });

  try {
    mp.processMessages(patchCatalog(messages));
  } catch (err) {
    console.error(err);
    errorText.value = String((err as Error)?.message || err);
  }
}

watch(
  () => props.messages,
  (msgs) => load(msgs || []),
  { immediate: true, deep: true }
);

onBeforeUnmount(() => {
  processor = null;
  surface.value = null;
});
</script>

<template>
  <div class="chat-a2ui">
    <div class="render-host a2ui-theme">
      <A2uiSurfaceHost v-if="surface" :surface="surface" />
      <p v-else-if="errorText" class="chat-a2ui-error">A2UI 渲染失败：{{ errorText }}</p>
      <p v-else class="placeholder">正在构建界面…</p>
    </div>
    <details v-if="lastAction" class="chat-a2ui-action">
      <summary>用户操作（尚未回传 Agent）</summary>
      <pre>{{ JSON.stringify(lastAction, null, 2) }}</pre>
    </details>
  </div>
</template>
