import { ref, type Ref } from "vue";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { basicCatalog } from "@a2ui/lit/v0_9";
import type { A2uiMessage } from "@/types/a2ui";

/**
 * Vue composable：把 A2UI JSON messages 交给官方 MessageProcessor。
 *
 * 流程：
 * 1. new MessageProcessor([basicCatalog], onAction)
 * 2. processMessages(messages) → createSurface / updateComponents / updateDataModel
 * 3. onSurfaceCreated → 得到 SurfaceModel，交给 <a2ui-surface> 渲染
 */
export function useA2uiSurface() {
  const surface: Ref<unknown | null> = ref(null);
  const lastAction: Ref<unknown | null> = ref(null);
  let processor: MessageProcessor | null = null;

  function clear() {
    surface.value = null;
    lastAction.value = null;
    processor = null;
  }

  function loadMessages(messages: A2uiMessage[]) {
    clear();
    const mp = new MessageProcessor([basicCatalog], (action: unknown) => {
      lastAction.value = action;
    });
    processor = mp;
    mp.onSurfaceCreated((s: unknown) => {
      surface.value = s;
    });

    // 确保 catalogId 与运行时 basicCatalog 一致
    const patched = messages.map((m) => {
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

    try {
      mp.processMessages(patched);
    } catch (err) {
      console.error(err);
      alert("A2UI 消息处理失败：" + String((err as Error)?.message || err));
    }
  }

  return { surface, lastAction, loadMessages, clear };
}
