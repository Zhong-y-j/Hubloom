import { createApp } from "vue";
import App from "./App.vue";
import "./styles.css";

// 注册官方 A2UI Lit 自定义元素（a2ui-surface + Basic Catalog 内各组件）
import { A2uiSurface } from "@a2ui/lit/v0_9";
void A2uiSurface;

createApp(App).mount("#app");
