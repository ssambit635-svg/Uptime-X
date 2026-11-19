import { expect, test } from '@playwright/test'
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { promisify } from 'node:util'

const run = promisify(execFile)

test('queue → bounded controlled HTTP check → persisted evidence → real charts and regional views', async ({
  page,
}) => {
  test.skip(
    !!process.env.E2E_BASE_URL,
    'The controlled helper is local-only, not a remote deployment test',
  )
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByLabel('Work email').fill(`measure-${crypto.randomUUID()}@example.com`)
  await page.getByLabel('Password', { exact: true }).fill('test-only-long-password!')
  await page.getByRole('button', { name: 'Create workspace', exact: true }).click()
  await page.getByRole('button', { name: 'Add website', exact: true }).click()
  await page.getByLabel('Monitor name').fill('Controlled HTTP evidence')
  await page.getByLabel('Website URL').fill('http://8.8.8.8/')
  await page.getByRole('dialog').getByRole('button', { name: 'Add website', exact: true }).click()
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'View measurements for Controlled HTTP evidence' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText(/No eligible HTTP timings/)).toBeVisible()
  const queued = page.waitForResponse(
    (response) => response.url().endsWith('/check') && response.status() === 202,
  )
  await dialog.getByRole('button', { name: 'Check now' }).click()
  const job = await (await queued).json()
  await expect(dialog.getByRole('status')).toContainText('not a success confirmation')
  const python =
    process.env.PYTHON ||
    (existsSync('../.venv/bin/python') ? resolve('../.venv/bin/python') : 'python')
  await run(python, ['tests/support/e2e_measure.py', job.job_ids[0]], {
    cwd: '..',
    env: {
      ...process.env,
      PYTHONPATH: 'backend',
      APP_ENV: 'test',
      DATABASE_URL: 'sqlite:///./.local/e2e.db',
    },
    timeout: 15_000,
  })
  await dialog.getByRole('button', { name: 'Refresh measurements' }).click()
  await expect(dialog.getByText('100.00%', { exact: true }).first()).toBeVisible()
  await expect(
    dialog.getByRole('img', { name: /Measured HTTP response time. 1 samples/ }),
  ).toBeVisible()
  await expect(
    dialog
      .getByRole('region', { name: 'Measured check history' })
      .getByText('200', { exact: true }),
  ).toBeVisible()
  await dialog.getByText('Accessible trend data (120 buckets)').click()
  await expect(dialog.getByRole('columnheader', { name: 'Bucket start (UTC)' })).toBeVisible()
  await dialog.evaluate((element) => {
    element.scrollTop = 0
  })
  await page.screenshot({
    path: test.info().outputPath('measurements-desktop.png'),
    fullPage: false,
  })
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(
    page.getByRole('button', { name: 'View measurements for Controlled HTTP evidence' }),
  ).toBeFocused()
  await page.getByRole('link', { name: 'Global monitor', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Regional worker health' })).toBeVisible()
  await expect(page.getByText('UNKNOWN / not reporting')).toBeVisible()
  // No worker loop was started: an individual result is not a fleet heartbeat.
  await page.getByRole('link', { name: 'Analytics', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Measured website performance' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Controlled HTTP evidence', exact: true }).click()
  await expect(dialog.getByRole('region', { name: 'Measured check history' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  const bounds = await dialog.boundingBox()
  expect(bounds!.y).toBeGreaterThanOrEqual(0)
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844)
  await dialog.evaluate((element) => {
    element.scrollTop = 0
  })
  await expect(
    page.getByRole('link', { name: 'Skip to content', includeHidden: true }),
  ).not.toBeInViewport()
  await page.screenshot({
    path: test.info().outputPath('measurements-mobile.png'),
    fullPage: false,
  })
  expect(errors).toEqual([])
})
