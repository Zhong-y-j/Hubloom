import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

/** 默认对接 Hubloom Serve（config http.port，常见 8765） */
const SERVE_TARGET =
  process.env.HUBLOOM_SERVE_URL || "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: SERVE_TARGET,
        changeOrigin: true,
      },
      "/health": {
        target: SERVE_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
