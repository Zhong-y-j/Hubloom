import { LitElement, html } from "lit";
import { ContextProvider } from "@lit/context";
import { Context } from "@a2ui/lit/v0_9";
import { renderMarkdown } from "@a2ui/markdown-it";

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

  render() {
    if (!this.surface) return html``;
    return html`<a2ui-surface .surface=${this.surface}></a2ui-surface>`;
  }
}

if (!customElements.get("a2ui-markdown-host")) {
  customElements.define("a2ui-markdown-host", A2uiMarkdownHost);
}

export { A2uiMarkdownHost };
