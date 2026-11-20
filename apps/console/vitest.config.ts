import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // The end-to-end tests spawn a real child process (the backend
    // server); worker_threads (vitest's default pool) cannot reliably
    // exec a subprocess in every sandboxed environment, so this test
    // suite runs each file in its own real process instead.
    pool: "forks",
    // The three e2e files each spawn a real uvicorn backend and, for
    // transform-journey, real git + compiled Rust CLI invocations too.
    // Running them concurrently (vitest's default) made each one compete
    // for CPU on shared CI runners, intermittently pushing a `waitFor`
    // past its timeout in whichever file lost the race -- a different
    // file each run, never a logic bug in any one of them. Running all
    // test files sequentially removes that contention; the ~20 other
    // files here are plain jsdom unit tests with no subprocess, so the
    // added wall-clock cost is small.
    fileParallelism: false,
  },
});
