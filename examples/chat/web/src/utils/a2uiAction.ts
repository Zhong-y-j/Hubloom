/** A2UI 客户端 action → 聊天用户消息（方式一：合成对话） */

export type A2uiClientAction = {
  name: string;
  context?: Record<string, unknown>;
  surfaceId?: string;
  sourceComponentId?: string;
  timestamp?: string;
};

/**
 * 将官方 A2uiClientAction 拼成一轮用户消息，供现有 /v1/chat 消费。
 *
 * 示例：
 * ```
 * [A2UI:confirm_add_community]
 * name: 阳光花园
 * address: 某某路 1 号
 * ```
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
