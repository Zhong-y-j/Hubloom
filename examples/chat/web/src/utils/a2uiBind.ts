/** 把字面量 value 改成 path 绑定，避免输入只留在 DOM、提交 context 为空。 */

import type { A2uiMessage } from "@/types/a2ui";

const EDITABLE = new Set([
  "TextField",
  "CheckBox",
  "Slider",
  "DateTimeInput",
  "ChoicePicker",
]);

function isPathRef(value: unknown): value is { path: string } {
  return (
    !!value &&
    typeof value === "object" &&
    typeof (value as { path?: unknown }).path === "string"
  );
}

function pathFromChecks(comp: Record<string, unknown>): string | null {
  const checks = comp.checks;
  if (!Array.isArray(checks)) return null;
  for (const check of checks) {
    if (!check || typeof check !== "object") continue;
    const cond = (check as { condition?: unknown }).condition;
    if (!cond || typeof cond !== "object") continue;
    const args = (cond as { args?: unknown }).args;
    if (!args || typeof args !== "object") continue;
    for (const raw of Object.values(args as Record<string, unknown>)) {
      if (isPathRef(raw) && raw.path.trim()) {
        const p = raw.path.trim();
        return p.startsWith("/") ? p : `/${p}`;
      }
    }
  }
  return null;
}

function pathFromId(compId: string, modelKeys: Set<string>): string | null {
  const cid = (compId || "").trim();
  if (!cid) return null;
  const base = cid.replace(/(Field|Input|Picker|Check|Checkbox|Slider|Date|Time)?$/i, "") || cid;
  const candidates = [base, base ? base[0].toLowerCase() + base.slice(1) : base, cid];
  for (const key of candidates) {
    if (modelKeys.has(key)) return `/${key}`;
  }
  if (base && /[A-Za-z]/.test(base[0])) {
    return `/${base[0].toLowerCase()}${base.slice(1)}`;
  }
  return null;
}

function collectModelKeys(messages: A2uiMessage[]): Set<string> {
  const keys = new Set<string>();
  for (const msg of messages) {
    const udm = (msg as { updateDataModel?: { value?: unknown } }).updateDataModel;
    const value = udm?.value;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      for (const k of Object.keys(value as Record<string, unknown>)) keys.add(k);
    }
  }
  return keys;
}

function ensureModelKey(
  messages: A2uiMessage[],
  surfaceId: string | undefined,
  path: string,
  seed: unknown,
): void {
  const key = path.replace(/^\//, "");
  if (!key || key.includes("/")) return;
  for (const msg of messages) {
    const udm = (msg as { updateDataModel?: Record<string, unknown> }).updateDataModel;
    if (!udm || typeof udm !== "object") continue;
    if (surfaceId && udm.surfaceId != null && String(udm.surfaceId) !== surfaceId) continue;
    const value = udm.value;
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const obj = value as Record<string, unknown>;
    if (!(key in obj)) obj[key] = seed ?? "";
    return;
  }
  if (!surfaceId) return;
  (messages as unknown[]).push({
    version: "v0.9",
    updateDataModel: {
      surfaceId,
      value: { [key]: seed ?? "" },
    },
  });
}

/** 就地修复 messages（返回同一引用，便于 patchCatalog 链式使用）。 */
export function bindEditableFieldPaths(messages: A2uiMessage[]): A2uiMessage[] {
  if (!messages?.length) return messages;
  const modelKeys = collectModelKeys(messages);
  for (const msg of messages) {
    const uc = (msg as { updateComponents?: Record<string, unknown> }).updateComponents;
    if (!uc || typeof uc !== "object") continue;
    const surfaceId = uc.surfaceId != null ? String(uc.surfaceId) : undefined;
    const comps = uc.components;
    if (!Array.isArray(comps)) continue;
    for (const raw of comps) {
      if (!raw || typeof raw !== "object") continue;
      const comp = raw as Record<string, unknown>;
      if (!EDITABLE.has(String(comp.component || ""))) continue;
      if (isPathRef(comp.value)) continue;
      const path =
        pathFromChecks(comp) || pathFromId(String(comp.id || ""), modelKeys);
      if (!path) continue;
      const seed = comp.value ?? "";
      comp.value = { path };
      ensureModelKey(messages, surfaceId, path, seed);
      modelKeys.add(path.replace(/^\//, ""));
    }
  }
  return messages;
}
