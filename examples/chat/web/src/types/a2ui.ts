/**
 * A2UI 消息类型（对齐协议 v0.9）。
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
