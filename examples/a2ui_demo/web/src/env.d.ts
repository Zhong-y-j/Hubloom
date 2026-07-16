/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

/** 官方 a2ui-* Web Components */
declare namespace JSX {
  interface IntrinsicElements {
    [elem: string]: unknown;
  }
}
