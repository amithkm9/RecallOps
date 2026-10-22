import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: { charts: ["recharts"], graph: ["@xyflow/react"] },
      },
    },
  },
  server: {
    proxy: { "/api": process.env.API_PROXY_TARGET || "http://127.0.0.1:8080" },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
