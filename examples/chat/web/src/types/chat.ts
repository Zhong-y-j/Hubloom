/** Chat API 类型（对齐 examples/chat SSE） */

export type ChatRole = "user" | "assistant";

export type AgentPhase =
  | "understanding"
  | "thinking"
  | "presenting"
  | "replying"
  | null;

export type ToolBlock = {
  title: string;
  body: string;
};

/** 正文与 A2UI 交错段（与后端 metadata.answer_parts 对齐） */
export type AnswerPart =
  | { type: "text"; text: string; channel?: "markdown" | "a2ui" }
  | { type: "a2ui" };

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  thought?: string;
  tools?: ToolBlock[];
  /** 本轮 SSE `a2ui` 事件中的消息数组（可选） */
  a2uiMessages?: import("@/types/a2ui").A2uiMessage[];
  /** replace 全量时递增，驱动 ChatA2uiBlock 重建 */
  a2uiReloadKey?: number;
  /** A2UI 链路侧栏文案（流式累积） */
  a2uiProse?: string;
  /** 有则按序渲染；无则回退 content → a2ui */
  answerParts?: AnswerPart[];
  streaming?: boolean;
  error?: boolean;
};

export type HistoryMessage = {
  role: ChatRole;
  content: string;
  thought?: string | null;
  tools?: ToolBlock[] | null;
  route?: string | null;
  /** 会话 metadata.a2ui，历史回放渲染 */
  a2ui?: import("@/types/a2ui").A2uiMessage[] | null;
  answer_parts?: AnswerPart[] | null;
  created_at?: string | null;
};
