/** A2UI 客户端 action → 结构化提交 / 展示文案 */

export type A2uiClientAction = {
  name: string;
  context?: Record<string, unknown>;
  surfaceId?: string;
  sourceComponentId?: string;
  timestamp?: string;
};

export type ChatActionPayload = {
  type: "submit" | "cancel";
  name: string;
  payload: Record<string, unknown>;
  surface_id?: string;
  source_component_id?: string;
};

/** 从按钮名粗判 cancel（其余视为 submit）。 */
export function inferActionType(name: string): "submit" | "cancel" {
  const n = String(name || "").trim().toLowerCase();
  if (
    n === "cancel" ||
    n === "取消" ||
    n.endsWith("_cancel") ||
    n.startsWith("cancel_") ||
    n.includes("cancel")
  ) {
    return "cancel";
  }
  return "submit";
}

export function toChatAction(action: A2uiClientAction): ChatActionPayload {
  const name = String(action?.name || "").trim() || "unknown";
  return {
    type: inferActionType(name),
    name,
    payload:
      action.context && typeof action.context === "object"
        ? { ...action.context }
        : {},
    surface_id: action.surfaceId,
    source_component_id: action.sourceComponentId,
  };
}

/** 气泡展示（非发给后端的合成闲聊）。 */
export function formatActionUserBubble(action: A2uiClientAction): string {
  const name = String(action?.name || "").trim() || "unknown";
  if (inferActionType(name) === "cancel") {
    return `已取消表单（${name}）`;
  }
  const lines = [`已提交表单：${name}`];
  const ctx = action?.context;
  if (ctx && typeof ctx === "object") {
    for (const [key, value] of Object.entries(ctx)) {
      if (value === undefined || value === null) continue;
      if (typeof value === "string" && !value.trim()) continue;
      const text =
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
          ? String(value)
          : JSON.stringify(value);
      lines.push(`${key}: ${text}`);
    }
  }
  return lines.join("\n");
}

/**
 * @deprecated live 表单应走 sendAction；仅无 waitingRunId 时兜底。
 */
export function formatA2uiActionAsChat(action: A2uiClientAction): string {
  const name = String(action?.name || "").trim() || "unknown";
  const lines = [`[A2UI:${name}]`];
  const ctx = action?.context;
  if (ctx && typeof ctx === "object") {
    for (const [key, value] of Object.entries(ctx)) {
      if (value === undefined || value === null) continue;
      if (typeof value === "string" && !value.trim()) continue;
      const text =
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean"
          ? String(value)
          : JSON.stringify(value);
      lines.push(`${key}: ${text}`);
    }
  }
  if (lines.length === 1) {
    lines.push("(无额外字段)");
  }
  return lines.join("\n");
}
