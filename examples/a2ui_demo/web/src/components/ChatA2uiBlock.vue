<script setup lang="ts">
/**
 * 单条助手消息内的 A2UI 渲染块。
 * 流式：messages 变长则只 processMessages 增量；reloadKey 变化则整包重载。
 */
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { basicCatalog } from "@a2ui/lit/v0_9";
import type { A2uiMessage } from "@/types/a2ui";
import type { A2uiClientAction } from "@/utils/a2uiAction";
import A2uiSurfaceHost from "@/components/A2uiSurfaceHost.vue";

const props = defineProps<{
  messages: A2uiMessage[];
  /** replace 权威全量时递增，强制 MessageProcessor 重建 */
  reloadKey?: number;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  action: [action: A2uiClientAction];
}>();

const surface = ref<unknown | null>(null);
const lastAction = ref<A2uiClientAction | null>(null);
const errorText = ref("");
const sentHint = ref("");

let processor: MessageProcessor | null = null;
let surfaceModel: { dataModel?: { get: (path: string) => unknown } } | null =
  null;
let appliedCount = 0;
let lastReloadKey = -1;

function asClientAction(raw: unknown): A2uiClientAction | null {
  if (!raw || typeof raw !== "object") return null;
  const obj = raw as Record<string, unknown>;
  const name = String(obj.name || "").trim();
  if (!name) return null;
  return {
    name,
    context:
      obj.context && typeof obj.context === "object"
        ? (obj.context as Record<string, unknown>)
        : {},
    surfaceId: obj.surfaceId != null ? String(obj.surfaceId) : undefined,
    sourceComponentId:
      obj.sourceComponentId != null ? String(obj.sourceComponentId) : undefined,
    timestamp: obj.timestamp != null ? String(obj.timestamp) : undefined,
  };
}

function enrichContext(action: A2uiClientAction): A2uiClientAction {
  const ctx = action.context || {};
  if (Object.keys(ctx).length > 0) return action;
  const root =
    surfaceModel?.dataModel?.get("/") ?? surfaceModel?.dataModel?.get("");
  if (root && typeof root === "object" && !Array.isArray(root)) {
    return { ...action, context: { ...(root as Record<string, unknown>) } };
  }
  return action;
}

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

function resetUiHints() {
  lastAction.value = null;
  errorText.value = "";
  sentHint.value = "";
}

function ensureProcessor(): MessageProcessor {
  if (processor) return processor;
  const mp = new MessageProcessor([basicCatalog], (raw: unknown) => {
    const parsed = asClientAction(raw);
    if (!parsed) return;
    const action = enrichContext(parsed);
    lastAction.value = action;
    if (props.disabled) {
      sentHint.value = "请等待上一轮回复结束后再操作";
      return;
    }
    sentHint.value = `已发送操作：${action.name}`;
    emit("action", action);
  });
  mp.onSurfaceCreated((s: unknown) => {
    surface.value = s;
    surfaceModel = s as { dataModel?: { get: (path: string) => unknown } };
  });
  processor = mp;
  return mp;
}

function loadAll(messages: A2uiMessage[]) {
  processor = null;
  surfaceModel = null;
  surface.value = null;
  resetUiHints();
  appliedCount = 0;
  if (!messages?.length) return;
  try {
    ensureProcessor().processMessages(patchCatalog(messages));
    appliedCount = messages.length;
  } catch (err) {
    console.error(err);
    errorText.value = String((err as Error)?.message || err);
  }
}

function appendSlice(slice: A2uiMessage[]) {
  if (!slice.length) return;
  try {
    ensureProcessor().processMessages(patchCatalog(slice));
    appliedCount += slice.length;
  } catch (err) {
    console.error(err);
    loadAll([...(props.messages || [])]);
  }
}

function syncFromProps() {
  const msgs = props.messages || [];
  const rk = props.reloadKey ?? 0;

  if (rk !== lastReloadKey) {
    lastReloadKey = rk;
    loadAll(msgs);
    return;
  }

  if (!msgs.length) {
    if (appliedCount > 0 || surface.value) loadAll([]);
    return;
  }

  if (!processor || appliedCount === 0) {
    loadAll(msgs);
    return;
  }

  if (msgs.length > appliedCount) {
    appendSlice(msgs.slice(appliedCount));
    return;
  }

  if (msgs.length < appliedCount) {
    loadAll(msgs);
  }
}

watch(
  () => [props.reloadKey ?? 0, props.messages?.length ?? 0] as const,
  () => syncFromProps(),
  { immediate: true }
);

/** 混排备注时非图片 URL 会得到坏图，直接隐藏 */
function onImgError(ev: Event) {
  const t = ev.target;
  if (!(t instanceof HTMLImageElement)) return;
  if (!t.closest(".chat-a2ui")) return;
  t.style.display = "none";
  const host = t.closest("a2ui-basic-image");
  if (host instanceof HTMLElement) host.style.display = "none";
}

onMounted(() => {
  window.addEventListener("error", onImgError, true);
});

onBeforeUnmount(() => {
  window.removeEventListener("error", onImgError, true);
  processor = null;
  surface.value = null;
  appliedCount = 0;
});
</script>

<template>
  <div class="chat-a2ui" :class="{ 'chat-a2ui-disabled': disabled }">
    <div class="render-host a2ui-theme">
      <A2uiSurfaceHost v-if="surface" :surface="surface" />
      <p v-else-if="errorText" class="chat-a2ui-error">A2UI 渲染失败：{{ errorText }}</p>
      <p v-else class="placeholder">正在构建界面…</p>
    </div>
    <p v-if="sentHint" class="chat-a2ui-sent">{{ sentHint }}</p>
  </div>
</template>
