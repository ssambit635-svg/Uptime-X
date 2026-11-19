import { expect, test } from '@playwright/test'
import type { APIRequestContext, BrowserContext, FrameLocator, Page } from '@playwright/test'

// Exercise a real cross-site iframe with the real built app + API. Deliberately
// remove *every* Cookie and Set-Cookie at the proxy boundary, including CHIPS.
// Merely enabling a third-party-cookie Chromium flag does not block CHIPS.
const parentOrigin = 'https://arena-preview.test'
const previewOrigin = 'https://uptimex-preview.test'
const previewBackend = process.env.E2E_PREVIEW_API_URL || 'http://127.0.0.1:8011'
const cookieBackend = 'http://127.0.0.1:8010'
const password = 'preview-test-only-password!'

async function cookieBlockedProxy(
  context: BrowserContext,
  upstream: APIRequestContext,
  cookieOnly = false,
) {
  await context.route(`${parentOrigin}/**`, (route) =>
    route.fulfill({
      contentType: 'text/html',
      body: `<!doctype html><html lang="en"><title>Embedded workspace</title><body style="margin:0"><iframe title="UptimeX preview" src="${previewOrigin}/" style="width:100vw;height:100vh;border:0"></iframe></body></html>`,
    }),
  )
  await context.route(`${previewOrigin}/**`, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const backend = cookieOnly && url.pathname.startsWith('/api/') ? cookieBackend : previewBackend
    // Keep the upstream request's cookie jar separate from the browser context.
    const response = await upstream.fetch(`${backend}${url.pathname}${url.search}`, {
      method: request.method(),
      data: request.postDataBuffer() ?? undefined,
      headers: { ...request.headers(), host: url.host, cookie: '' },
      maxRedirects: 0,
    })
    const headers = response.headers()
    delete headers['set-cookie']
    await route.fulfill({ response, headers })
  })
}

async function openPreview(page: Page) {
  await page.goto(parentOrigin)
  return page.frameLocator('iframe[title="UptimeX preview"]')
}

async function register(frame: FrameLocator) {
  const email = `preview-${crypto.randomUUID()}@example.com`
  await frame.getByLabel('Work email').fill(email)
  await frame.getByLabel('Password', { exact: true }).fill(password)
  await frame.getByRole('button', { name: 'Create workspace', exact: true }).click()
  await expect(frame.getByRole('heading', { name: 'Overview' })).toBeVisible()
  await expect(frame.getByText('A home for your first website.')).toBeVisible()
  return email
}

async function login(frame: FrameLocator, email: string) {
  await frame.getByRole('button', { name: 'Sign in', exact: true }).click()
  await frame.getByLabel('Work email').fill(email)
  await frame.getByLabel('Password', { exact: true }).fill(password)
  await frame.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(frame.getByRole('heading', { name: 'Overview' })).toBeVisible()
}

test.describe('embedded preview session regressions', () => {
  test.skip(
    Boolean(process.env.E2E_BASE_URL) && !process.env.E2E_PREVIEW_API_URL,
    'Provide an explicitly enabled, disposable preview API to test an external deployment.',
  )

  test('register → protected write → reload → logout → existing-account login without any cookies', async ({
    page,
    context,
    request: upstream,
  }) => {
    const errors: string[] = []
    const monitorResponses: number[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/v1/monitors') {
        monitorResponses.push(response.status())
      }
    })
    await cookieBlockedProxy(context, upstream)
    const frame = await openPreview(page)
    const email = await register(frame)
    await frame.getByRole('button', { name: 'Add website', exact: true }).click()
    await frame.getByLabel('Monitor name').fill('Cookie-free website')
    await frame.getByLabel('Website URL').fill('https://8.8.8.8')
    await frame
      .getByRole('dialog')
      .getByRole('button', { name: 'Add website', exact: true })
      .click()
    await expect(frame.getByRole('button', { name: 'Edit Cookie-free website' })).toBeVisible()
    await page.reload()
    await expect(frame.getByRole('button', { name: 'Edit Cookie-free website' })).toBeVisible()
    expect(
      await frame.locator('body').evaluate(() => ({
        session: Boolean(sessionStorage.getItem('uptimex.preview-session.v1')),
        local: localStorage.getItem('uptimex.preview-session.v1'),
      })),
    ).toEqual({ session: true, local: null })
    await frame.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(frame.getByRole('heading', { name: 'Create your workspace' })).toBeVisible()
    expect(
      await frame
        .locator('body')
        .evaluate(() => sessionStorage.getItem('uptimex.preview-session.v1')),
    ).toBeNull()
    await page.reload()
    await expect(frame.getByRole('heading', { name: 'Create your workspace' })).toBeVisible()
    await login(frame, email)
    await expect(frame.getByRole('button', { name: 'Edit Cookie-free website' })).toBeVisible()
    await page.reload()
    await expect(frame.getByRole('button', { name: 'Edit Cookie-free website' })).toBeVisible()
    expect(await context.cookies()).toEqual([])
    expect(monitorResponses.length).toBeGreaterThan(3)
    expect(monitorResponses.every((status) => status === 200 || status === 201)).toBe(true)
    expect(errors).toEqual([])
  })

  test('storage-denied browsers can still sign in and sign out using a page-lifetime session', async ({
    page,
    context,
    request: upstream,
  }) => {
    await cookieBlockedProxy(context, upstream)
    await context.addInitScript(() => {
      for (const operation of ['getItem', 'setItem', 'removeItem']) {
        Object.defineProperty(Storage.prototype, operation, {
          value: () => {
            throw new DOMException('Storage denied for embedded content', 'SecurityError')
          },
        })
      }
    })
    const frame = await openPreview(page)
    const email = await register(frame)
    await frame.getByRole('button', { name: 'Sign out', exact: true }).click()
    await login(frame, email)
    await expect(frame.getByText('A home for your first website.')).toBeVisible()
    await page.reload()
    // Nothing can persist when the browser denies both cookies and all storage.
    await expect(frame.getByRole('heading', { name: 'Create your workspace' })).toBeVisible()
    expect(await context.cookies()).toEqual([])
  })

  test('a cookie-only server never shows a fake authenticated dashboard when cookies are blocked', async ({
    page,
    context,
    request: upstream,
  }) => {
    test.skip(Boolean(process.env.E2E_BASE_URL), 'Uses the isolated cookie-only API on port 8010.')
    await cookieBlockedProxy(context, upstream, true)
    const frame = await openPreview(page)
    const email = `blocked-${crypto.randomUUID()}@example.com`
    await frame.getByLabel('Work email').fill(email)
    await frame.getByLabel('Password', { exact: true }).fill(password)
    await frame.getByRole('button', { name: 'Create workspace', exact: true }).click()
    await expect(frame.getByRole('alert')).toContainText('Your account was created')
    await expect(frame.getByRole('link', { name: /Open preview in a new tab/ })).toHaveAttribute(
      'href',
      `${previewOrigin}/`,
    )
    await expect(frame.getByRole('heading', { name: 'Overview' })).not.toBeVisible()
    await frame.getByRole('button', { name: 'Sign in', exact: true }).click()
    await frame.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(frame.getByRole('alert')).toContainText('This browser blocked the sign-in session')
    await expect(frame.getByRole('heading', { name: 'Welcome back' })).toBeVisible()
  })
})
