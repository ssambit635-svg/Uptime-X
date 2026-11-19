import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const python =
  process.env.PYTHON ||
  (existsSync('../.venv/bin/python') ? resolve('../.venv/bin/python') : 'python')
const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:4173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL,
    ...devices['Desktop Chrome'],
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
          args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-zygote'],
        }
      : undefined,
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          command: `"${python}" -m alembic upgrade head && "${python}" -m uvicorn app.main:app --host 0.0.0.0 --port 8010 --no-proxy-headers`,
          cwd: '..',
          env: {
            PYTHONPATH: 'backend',
            DATABASE_URL: 'sqlite:///./.local/e2e.db',
            APP_ENV: 'test',
            SESSION_COOKIE_SECURE: 'false',
            EMBEDDED_PREVIEW: 'false',
          },
          url: 'http://127.0.0.1:8010/api/v1/health',
          reuseExistingServer: false,
        },
        {
          command: 'npm run dev -- --port 4173 --strictPort',
          env: { API_PROXY_TARGET: 'http://127.0.0.1:8010' },
          url: baseURL,
          reuseExistingServer: false,
        },
        {
          command: `npm run build --prefix frontend && "${python}" -m alembic upgrade head && "${python}" -m uvicorn app.main:app --host 0.0.0.0 --port 8011 --no-proxy-headers --no-access-log`,
          cwd: '..',
          env: {
            PYTHONPATH: 'backend',
            DATABASE_URL: 'sqlite:///./.local/preview-e2e.db',
            APP_ENV: 'test',
            SESSION_COOKIE_SECURE: 'false',
            EMBEDDED_PREVIEW: 'true',
            FRONTEND_DIST: 'frontend/dist',
          },
          url: 'http://127.0.0.1:8011/api/v1/health',
          timeout: 120_000,
          reuseExistingServer: false,
        },
      ],
})
