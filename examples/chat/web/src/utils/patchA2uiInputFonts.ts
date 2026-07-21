/**
 * Basic Catalog 的 input/textarea 未设字号/字体，浏览器 UA 不继承，
 * 导致输入文字偏小且仍是系统字体。向相关组件 shadowRoot 注入样式。
 */

const FORM_TAGS = new Set([
  "A2UI-BASIC-TEXTFIELD",
  "A2UI-DATETIMEINPUT",
  "A2UI-CHOICEPICKER",
  "A2UI-CHECKBOX",
  "A2UI-BASIC-BUTTON",
  "A2UI-SLIDER",
  "A2UI-BASIC-TEXT",
]);

const MARK = "__hubloomInputFont";
const OBS_MARK = "__hubloomFontObs";

const FONT_UI = `"Plus Jakarta Sans", "Noto Sans SC", sans-serif`;
const FONT_DISPLAY = `"Outfit", "Noto Sans SC", sans-serif`;

const CSS_TEXT = `
  :host {
    font-family: ${FONT_UI};
  }
  .a2ui-textfield,
  input:not([type="checkbox"]):not([type="radio"]),
  textarea,
  select {
    font-family: ${FONT_UI} !important;
    font-size: 0.96rem !important;
    font-weight: 500 !important;
    line-height: 1.45 !important;
    letter-spacing: 0.01em;
  }
  label {
    font-family: ${FONT_UI} !important;
    letter-spacing: 0.02em;
  }
  .a2ui-button {
    font-family: ${FONT_UI} !important;
    font-size: 0.94rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
  }
  .chip {
    font-family: ${FONT_UI} !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
  }
  .options label {
    font-family: ${FONT_UI} !important;
    font-size: 0.9rem !important;
    font-weight: 500 !important;
  }
  h1, h2, h3, h4, h5 {
    font-family: ${FONT_DISPLAY} !important;
    letter-spacing: -0.02em;
    font-weight: 600;
  }
  p, .markdown-body {
    font-family: ${FONT_UI} !important;
  }
`;

let sheet: CSSStyleSheet | null = null;

function getSheet(): CSSStyleSheet {
  if (!sheet) {
    sheet = new CSSStyleSheet();
    sheet.replaceSync(CSS_TEXT);
  }
  return sheet;
}

function patchShadow(el: Element): void {
  const root = (el as HTMLElement).shadowRoot;
  if (!root || (el as HTMLElement & { [MARK]?: boolean })[MARK]) return;
  (el as HTMLElement & { [MARK]?: boolean })[MARK] = true;
  try {
    root.adoptedStyleSheets = [...root.adoptedStyleSheets, getSheet()];
  } catch {
    if (!root.querySelector(`style[${MARK}]`)) {
      const style = document.createElement("style");
      style.setAttribute(MARK, "1");
      style.textContent = CSS_TEXT;
      root.appendChild(style);
    }
  }
}

function scanNode(node: Node, observeShadow: (root: ShadowRoot) => void): void {
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  const el = node as HTMLElement;
  if (FORM_TAGS.has(el.tagName)) patchShadow(el);

  const sr = el.shadowRoot;
  if (sr) {
    observeShadow(sr);
    sr.querySelectorAll("*").forEach((child) => {
      if (FORM_TAGS.has(child.tagName)) patchShadow(child);
      const nested = (child as HTMLElement).shadowRoot;
      if (nested) {
        observeShadow(nested);
        nested.querySelectorAll("*").forEach((deep) => {
          if (FORM_TAGS.has(deep.tagName)) patchShadow(deep);
        });
      }
    });
  }

  el.querySelectorAll("*").forEach((child) => {
    if (FORM_TAGS.has(child.tagName)) patchShadow(child);
    const childSr = (child as HTMLElement).shadowRoot;
    if (childSr) {
      observeShadow(childSr);
      childSr.querySelectorAll("*").forEach((nested) => {
        if (FORM_TAGS.has(nested.tagName)) patchShadow(nested);
      });
    }
  });
}

/** 单次扫描（surface 更新后补扫）。 */
export function patchA2uiInputFonts(root: ParentNode): void {
  const noop = () => {};
  scanNode(root as Node, noop);
  if (root instanceof Element && root.shadowRoot) {
    scanNode(root.shadowRoot as unknown as Node, noop);
  }
  root.querySelectorAll("*").forEach((el) => {
    const sr = (el as HTMLElement).shadowRoot;
    if (sr) scanNode(sr as unknown as Node, noop);
  });
}

/** 持续观察子树（含嵌套 open shadowRoot）；返回 disconnect。 */
export function watchA2uiInputFonts(root: ParentNode): () => void {
  const observers: MutationObserver[] = [];

  const observeShadow = (sr: ShadowRoot) => {
    const host = sr.host as HTMLElement & { [OBS_MARK]?: boolean };
    if (host[OBS_MARK]) return;
    host[OBS_MARK] = true;
    const mo = new MutationObserver((records) => {
      for (const rec of records) {
        rec.addedNodes.forEach((n) => scanNode(n, observeShadow));
      }
    });
    mo.observe(sr, { childList: true, subtree: true });
    observers.push(mo);
  };

  scanNode(root as Node, observeShadow);

  const top = new MutationObserver((records) => {
    for (const rec of records) {
      rec.addedNodes.forEach((n) => scanNode(n, observeShadow));
    }
  });
  top.observe(root, { childList: true, subtree: true });
  observers.push(top);

  return () => {
    for (const mo of observers) mo.disconnect();
  };
}
