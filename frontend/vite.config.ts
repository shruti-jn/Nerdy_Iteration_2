import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { avatarkitVitePlugin } from "@spatialwalk/avatarkit/vite";

export default defineConfig({
  plugins: [react(), avatarkitVitePlugin()],
  server: {
    proxy: {
      "/session": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
      "/topics": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    exclude: ["e2e/**", "node_modules/**"],
  },
});
