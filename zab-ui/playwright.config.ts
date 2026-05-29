import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const zabRepoRoot = path.resolve(__dirname, '..')
const testPort = process.env.ZAB_E2E_PORT ?? '18742'
/** Si défini (URL complète sans slash final), les tests frappent cette instance et aucun serveur local n’est démarré. */
const remoteBase =
  typeof process.env.PLAYWRIGHT_BASE_URL === 'string' ? process.env.PLAYWRIGHT_BASE_URL.trim() : ''
const baseURL =
  remoteBase.length > 0 ? remoteBase.replace(/\/$/, '') : `http://127.0.0.1:${testPort}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  ...(remoteBase.length > 0
    ? {}
    : {
        webServer: {
          command: `bash "${path.join(zabRepoRoot, 'scripts/zab-e2e-dashboard.sh')}"`,
          cwd: zabRepoRoot,
          url: `${baseURL}/api/health`,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
          stdout: 'pipe',
          stderr: 'pipe',
        },
      }),
})
