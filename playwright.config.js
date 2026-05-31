const { defineConfig } = require("@playwright/test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:3000";
const e2eDataDir = process.env.PLAYWRIGHT_DATA_DIR || path.join(os.tmpdir(), "jing-an-agent-task-e2e-data");
const chromeApp = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browserChannel = process.env.PLAYWRIGHT_CHANNEL || (fs.existsSync(chromeApp) ? "chrome" : undefined);
const localNoProxy = ["127.0.0.1", "localhost", "::1"];

for (const key of ["NO_PROXY", "no_proxy"]) {
  const current = process.env[key] || "";
  const values = new Set(current.split(",").map((item) => item.trim()).filter(Boolean));
  localNoProxy.forEach((value) => values.add(value));
  process.env[key] = Array.from(values).join(",");
}

module.exports = defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 5_000
  },
  workers: 1,
  use: {
    baseURL,
    browserName: "chromium",
    channel: browserChannel,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 10_000
  },
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : {
        command: `DATA_DIR=${JSON.stringify(e2eDataDir)} python3 app/server.py --host 127.0.0.1 --port 3000`,
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 15_000
      }
});
