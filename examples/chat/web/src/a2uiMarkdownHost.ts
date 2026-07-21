import { LitElement, html } from "lit";
import { ContextProvider } from "@lit/context";
import { Context } from "@a2ui/lit/v0_9";
import { renderMarkdown } from "@a2ui/markdown-it";
import {
  patchA2uiInputFonts,
  watchA2uiInputFonts,
} from "@/utils/patchA2uiInputFonts";

/**
 * Lit 宿主：注入 markdown Context，并渲染官方 <a2ui-surface>。
 *
 * 渲染链路：
 *   Vue 传入 SurfaceModel
 *     → 本组件注入 Context.markdown（否则 Text h2 会显示 "##"）
 *     → <a2ui-surface> 按 Catalog 把 Column/TextField/Button… 画成 Web Components
 */
class A2uiMarkdownHost extends LitElement {
  static properties = {
    surface: { attribute: false },
  };

  declare surface: unknown;

  #stopFontWatch: (() => void) | null = null;

  constructor() {
    super();
    this.surface = undefined;
    new ContextProvider(this, {
      context: Context.markdown,
      initialValue: renderMarkdown,
    });
  }

  createRenderRoot() {
    // light DOM：页面 --a2ui-* CSS 变量可传到 Basic Catalog
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this.#stopFontWatch?.();
    this.#stopFontWatch = watchA2uiInputFonts(this);
  }

  disconnectedCallback() {
    this.#stopFontWatch?.();
    this.#stopFontWatch = null;
    super.disconnectedCallback();
  }

  updated(changed: Map<string, unknown>) {
    super.updated(changed);
    if (changed.has("surface")) {
      // Lit 更新 / shadow 就绪后再补扫
      requestAnimationFrame(() => patchA2uiInputFonts(this));
      setTimeout(() => patchA2uiInputFonts(this), 50);
    }
  }

  render() {
    if (!this.surface) return html``;
    return html`<a2ui-surface .surface=${this.surface}></a2ui-surface>`;
  }
}

if (!customElements.get("a2ui-markdown-host")) {
  customElements.define("a2ui-markdown-host", A2uiMarkdownHost);
}

export { A2uiMarkdownHost };
