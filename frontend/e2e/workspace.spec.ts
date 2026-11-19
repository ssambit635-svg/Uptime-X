import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const password = 'test-only-long-password!'
async function register(page: Page) {
  const email = `e2e-${crypto.randomUUID()}@example.com`
  await page.goto('/')
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Create workspace', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await expect(page.getByText('A home for your first website.')).toBeVisible()
  return email
}
async function addMonitor(page: Page, name: string, url: string) {
  await page.getByRole('button', { name: 'Add website', exact: true }).click()
  await page.getByLabel('Monitor name').fill(name)
  await page.getByLabel('Website URL').fill(url)
  await page.getByRole('dialog').getByRole('button', { name: 'Add website', exact: true }).click()
}

test('register, persist, edit, pause/resume, sign in, and delete a real configuration', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const email = await register(page)
  await addMonitor(page, 'Main website', 'https://8.8.8.8')
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible()
  await expect(page.getByText('No check data', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Pause Main website' })).toBeVisible()
  await page.getByRole('button', { name: 'Pause Main website' }).click()
  await expect(page.getByText('PAUSED', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Resume Main website' }).click()
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Edit Main website' }).click()
  await page.getByLabel('Monitor name').fill('Marketing website')
  await page.getByLabel('Check interval').selectOption('600')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByRole('button', { name: 'Edit Marketing website' })).toBeVisible()
  await page.getByLabel('Search websites').fill('no-matches')
  await expect(page.getByText('No websites match.')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await page.getByRole('link', { name: /Websites/ }).click()
  await expect(page.getByRole('heading', { name: 'Websites', level: 1 })).toBeVisible()
  const skip = page.getByRole('link', { name: 'Skip to content' })
  await skip.focus()
  await skip.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  await expect(page).toHaveURL(/#websites$/)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await page.getByLabel('Work email').fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Delete Marketing website' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Marketing website' }).click()
  await page.getByRole('button', { name: 'Keep monitor' }).click()
  await expect(page.getByRole('button', { name: 'Delete Marketing website' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Marketing website' }).click()
  await page.getByRole('button', { name: 'Delete monitor', exact: true }).click()
  await expect(page.getByText('A home for your first website.')).toBeVisible()
  expect(errors).toEqual([])
})

test('private destinations are rejected and modal keyboard focus is restored', async ({ page }) => {
  await register(page)
  const trigger = page.getByRole('button', { name: 'Add website', exact: true })
  await addMonitor(page, 'Forbidden endpoint', 'http://127.0.0.1')
  await expect(page.getByRole('alert')).toContainText('Private, local, reserved and metadata')
  await expect(page.getByLabel('Monitor name')).toHaveValue('Forbidden endpoint')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).not.toBeVisible()
  await expect(trigger).toBeFocused()
})

test('another account cannot read or mutate an owner’s monitor', async ({ page, browser }) => {
  await register(page)
  await addMonitor(page, 'Private configuration', 'https://1.1.1.1')
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible()
  const owned = await (await page.request.get('/api/v1/monitors')).json()
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL || 'http://127.0.0.1:4173',
  })
  const other = await context.newPage()
  await register(other)
  const response = await other.request.get(`/api/v1/monitors/${owned.items[0].id}`)
  expect(response.status()).toBe(404)
  const change = await other.request.post(`/api/v1/monitors/${owned.items[0].id}/pause`, {
    headers: { 'X-UptimeX-Client': 'web' },
  })
  expect(change.status()).toBe(404)
  await expect(other.getByText('A home for your first website.')).toBeVisible()
  await context.close()
})

test('mobile layout stays within the viewport and navigation works by keyboard', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await register(page)
  await addMonitor(page, 'Mobile website', 'https://8.8.4.4')
  await expect(page.getByText('UNKNOWN', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await menu.click()
  await expect(page.getByRole('link', { name: /Websites/ })).toBeInViewport()
  await page.keyboard.press('Escape')
  await expect(menu).toBeFocused()
  await menu.click()
  await page.getByRole('link', { name: /Websites/ }).click()
  await expect(page.getByRole('heading', { name: 'Websites', level: 1 })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
})
