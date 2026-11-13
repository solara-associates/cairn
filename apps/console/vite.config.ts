import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/healthz": "http://localhost:8080",
      "/readyz": "http://localhost:8080",
    },
  },
});
