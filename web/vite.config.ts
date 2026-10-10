/// <reference types="vitest/config" />
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const serverPort = process.env.NOTEBOOKLM_SERVER_PORT ?? "8000";

export default defineConfig({
  base: "/ui/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: {
    outDir: "../src/notebooklm/server/static/ui",
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    proxy: { "/v1": { target: `http://127.0.0.1:${serverPort}`, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
