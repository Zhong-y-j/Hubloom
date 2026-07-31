/** Chat API 类型（对齐 Hubloom Serve SSE） */

export type ChatRole = "user" | "assistant";

export type AgentPhase = "deciding" | "acting" | "replying" | null;

export type ToolBlock = {
  title: string;
  body: string;
};

export type PendingAwait = {
  runId: string;
  awaitToken: string;
  kind: string;
  prompt: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  thought?: string;
  tools?: ToolBlock[];
  streaming?: boolean;
  error?: boolean;
  /** conversation source：user / event / action … */
  source?: string;
  /** interactive 挂起时的追问提示（助手侧展示） */
  awaitPrompt?: boolean;
};

export type HistoryMessage = {
  role: ChatRole;
  content: string;
  created_at?: string | null;
  source?: string | null;
  /** 仅 include_thought=true 时返回 */
  thought?: string | null;
  /** 本轮折叠的工具调用/返回，对齐实时 SSE */
  tools?: ToolBlock[] | null;
};
