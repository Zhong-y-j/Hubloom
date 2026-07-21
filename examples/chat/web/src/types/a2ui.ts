/**
 * A2UI 消息与场景类型（对齐协议 v0.9 / samples 形状）。
 * 本 demo 不接后端，数据全部来自 src/data/scenarios.ts。
 */

export type A2uiVersion = "v0.9" | "v0.9.1";

export type DynamicString = string | { path: string };

export type A2uiComponent = {
  id: string;
  component: string;
  [key: string]: unknown;
};

export type A2uiMessage =
  | {
      version: A2uiVersion;
      createSurface: { surfaceId: string; catalogId: string };
    }
  | {
      version: A2uiVersion;
      updateComponents: {
        surfaceId: string;
        components: A2uiComponent[];
      };
    }
  | {
      version: A2uiVersion;
      updateDataModel: {
        surfaceId: string;
        path: string;
        value: unknown;
      };
    }
  | {
      version: A2uiVersion;
      deleteSurface: { surfaceId: string };
    };

export type Scenario = {
  id: string;
  title: string;
  userSays: string;
  agentSays: string;
  why: string;
  /** Agent 会推送的 A2UI 消息数组（本 demo 写死在 TS 里） */
  messages: A2uiMessage[];
};
