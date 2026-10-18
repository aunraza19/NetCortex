import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const python = path.resolve(
  "../../.venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);

export default defineConfig({
  testDir: "./e2e",
  testMatch: "runtime-contract.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3002",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: `"${python}" ../../eval/api_demo.py --port 8137 --awaiting`,
      url: "http://127.0.0.1:8137/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3002",
      url: "http://127.0.0.1:3002",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_MODE: "live",
        NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8137",
      },
    },
  ],
});
