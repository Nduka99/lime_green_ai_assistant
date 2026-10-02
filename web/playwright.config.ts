import { defineConfig } from "@playwright/test";

// The thread in a real browser against the built app, with the API answered by
// each test (`page.route`), so runs are fast and need no model servers. It uses the
// installed Microsoft Edge (Playwright's `msedge` channel): no browser download.
export default defineConfig({
  testDir: "e2e",
  // Reduced motion: accessibility checks then measure settled colours, not a frame of
  // a fade, and the reduced-motion styles are exercised.
  use: { baseURL: "http://127.0.0.1:4173", channel: "msedge", reducedMotion: "reduce" },
  webServer: {
    command:
      "npx vite build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
  },
});
