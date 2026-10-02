/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the app on 5173 and passes /api to a running `limespec serve`
// (API_URL, default its port 8090). `npm run build` writes web/dist, which
// `limespec serve` then serves itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8090" },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/api-types.ts", "src/**/*.test.{ts,tsx}"],
      thresholds: { lines: 100, branches: 100, functions: 100, statements: 100 },
    },
  },
});
