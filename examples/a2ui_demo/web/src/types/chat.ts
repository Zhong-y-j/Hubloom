/** Chat API 类型（对齐 examples/chat SSE） */

export type ChatRole = "user" | "assistant";

export type AgentPhase = "understanding" | "thinking" | "replying" | null;

export type ToolBlock = {
  title: string;
  body: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  thought?: string;
  tools?: ToolBlock[];
  streaming?: boolean;
  error?: boolean;
};

export type HistoryMessage = {
  role: ChatRole;
  content: string;
  thought?: string | null;
  tools?: ToolBlock[] | null;
  route?: string | null;
  created_at?: string | null;
};
