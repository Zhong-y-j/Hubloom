<script setup lang="ts">
/**
 * 单条助手消息内的 A2UI 渲染块。
 * 每条消息独立 MessageProcessor；Button action 向上抛出，由 Chat 拼成用户消息发送。
 */
import { onBeforeUnmount, ref, watch } from "vue";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { basicCatalog } from "@a2ui/lit/v0_9";
import type { A2uiMessage } from "@/types/a2ui";
import type { A2uiClientAction } from "@/utils/a2uiAction";
import A2uiSurfaceHost from "@/components/A2uiSurfaceHost.vue";

const props = defineProps<{
  messages: A2uiMessage[];
  /** 忙碌时仍可展示上次 action，但不重复点击发送（由父级 send 门禁） */
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

/** 按钮未声明 context 时，用 surface Data Model 根对象补字段 */
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

function load(messages: A2uiMessage[]) {
  processor = null;
  surfaceModel = null;
  surface.value = null;
  lastAction.value = null;
  errorText.value = "";
  sentHint.value = "";
  if (!messages?.length) return;

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
  processor = mp;
  mp.onSurfaceCreated((s: unknown) => {
    surface.value = s;
    surfaceModel = s as { dataModel?: { get: (path: string) => unknown } };
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
  <div class="chat-a2ui" :class="{ 'chat-a2ui-disabled': disabled }">
    <div class="render-host a2ui-theme">
      <A2uiSurfaceHost v-if="surface" :surface="surface" />
      <p v-else-if="errorText" class="chat-a2ui-error">A2UI 渲染失败：{{ errorText }}</p>
      <p v-else class="placeholder">正在构建界面…</p>
    </div>
    <p v-if="sentHint" class="chat-a2ui-sent">{{ sentHint }}</p>
    <details v-if="lastAction" class="chat-a2ui-action">
      <summary>最近一次操作载荷</summary>
      <pre>{{ JSON.stringify(lastAction, null, 2) }}</pre>
    </details>
  </div>
</template>
