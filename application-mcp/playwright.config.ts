import { defineConfig } from "@playwright/test";
import path from "node:path";
process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(
  "node_modules/.cache/ms-playwright",
);
export default defineConfig({
  testDir: "./test/browser",
  workers: 1,
  use: { headless: true },
  reporter: "list",
});
