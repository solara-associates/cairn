import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // The end-to-end test spawns a real child process (the backend
    // server); worker_threads (vitest's default pool) cannot reliably
    // exec a subprocess in every sandboxed environment, so this test
    // suite runs each file in its own real process instead.
    pool: "forks",
  },
});
