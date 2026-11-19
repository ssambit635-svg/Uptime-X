import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, request } from './api'

const fetchMock = vi.fn<typeof fetch>()
afterEach(() => fetchMock.mockReset())

function respond(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    fetchMock.mockImplementation(
      async () => new Response(status === 204 ? null : JSON.stringify(body), { status }),
    ),
  )
}

describe('same-origin API client', () => {
  it('sends JSON, the CSRF header, and same-origin credentials', async () => {
    respond({ id: 'u1' })
    await api.authenticate('register', 'owner@example.com', 'a-long-password')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/auth/register')
    expect(options?.credentials).toBe('same-origin')
    expect(options?.headers).toMatchObject({
      'Content-Type': 'application/json',
      'X-UptimeX-Client': 'web',
    })
    expect(options?.body).toBe(
      JSON.stringify({ email: 'owner@example.com', password: 'a-long-password' }),
    )
  })
  it('handles empty 204 responses without JSON parsing', async () => {
    respond(null, 204)
    await expect(api.logout()).resolves.toBeUndefined()
  })
  it('surfaces safe server errors', async () => {
    respond({ error: { code: 'UNSAFE_TARGET', message: 'Private addresses are blocked.' } }, 422)
    await expect(request('/monitors')).rejects.toMatchObject({
      message: 'Private addresses are blocked.',
      status: 422,
      code: 'UNSAFE_TARGET',
    })
  })
  it('handles validation messages and non-JSON failures', async () => {
    respond(
      { error: { fields: [{ field: 'interval_seconds', message: 'Invalid interval' }] } },
      422,
    )
    await expect(request('/monitors')).rejects.toThrow('interval seconds: Invalid interval')
    fetchMock.mockResolvedValue(new Response('Bad gateway', { status: 502 }))
    await expect(request('/monitors')).rejects.toBeInstanceOf(ApiError)
  })
  it('shows network failures rather than an empty successful workspace', async () => {
    vi.stubGlobal('fetch', fetchMock.mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.monitors()).rejects.toMatchObject({ status: 0, code: 'NETWORK_ERROR' })
  })
  it('emits session expiry for protected resources, not login failures', async () => {
    const event = vi.fn()
    window.addEventListener('uptimex:session-expired', event)
    respond({ error: { message: 'Sign in again' } }, 401)
    await api.monitors().catch(() => {})
    expect(event).toHaveBeenCalledTimes(1)
    await api.authenticate('login', 'owner@example.com', 'wrong-password').catch(() => {})
    expect(event).toHaveBeenCalledTimes(1)
    window.removeEventListener('uptimex:session-expired', event)
  })
})

describe('session establishment', () => {
  const user = { id: 'u1', email: 'owner@example.com', created_at: '2026-11-19T00:00:00Z' }
  const previewSession = {
    token: 'A'.repeat(43),
    expires_at: new Date(Date.now() + 3_600_000).toISOString(),
  }

  it('verifies the session before returning an authenticated user', async () => {
    respond(user)
    await expect(api.authenticate('login', user.email, 'a-long-password')).resolves.toEqual(user)
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/auth/login',
      '/api/v1/auth/me',
    ])
  })

  it('does not treat a 200 login with a rejected session as successful', async () => {
    vi.stubGlobal(
      'fetch',
      fetchMock
        .mockResolvedValueOnce(new Response(JSON.stringify(user), { status: 200 }))
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ error: { code: 'UNAUTHENTICATED', message: 'Sign in' } }), {
            status: 401,
          }),
        ),
    )
    await expect(api.authenticate('login', user.email, 'a-long-password')).rejects.toMatchObject({
      code: 'SESSION_NOT_ESTABLISHED',
    })
  })

  it('uses an explicitly issued preview session when cookies are unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      fetchMock
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ...user, preview_session: previewSession }), {
            status: 200,
          }),
        )
        .mockResolvedValueOnce(new Response(JSON.stringify(user), { status: 200 })),
    )
    const result = await api.authenticate('login', user.email, 'a-long-password')
    expect(result).toEqual(user)
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({
      'X-UptimeX-Preview-Session': previewSession.token,
    })
    expect(sessionStorage.getItem('uptimex.preview-session.v1')).not.toBeNull()
    expect(localStorage.getItem('uptimex.preview-session.v1')).toBeNull()
  })

  it('still establishes a preview session if browser storage is denied', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Denied', 'SecurityError')
    })
    vi.stubGlobal(
      'fetch',
      fetchMock
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ ...user, preview_session: previewSession }), {
            status: 200,
          }),
        )
        .mockResolvedValueOnce(new Response(JSON.stringify(user), { status: 200 })),
    )
    await expect(api.authenticate('login', user.email, 'a-long-password')).resolves.toEqual(user)
    expect(fetchMock.mock.calls[1][1]?.headers).toMatchObject({
      'X-UptimeX-Preview-Session': previewSession.token,
    })
  })

  it('clears the preview credential after a successful logout', async () => {
    const { storePreviewSession, getPreviewSessionToken } = await import('./previewSession')
    storePreviewSession(previewSession)
    respond(null, 204)
    await api.logout()
    expect(getPreviewSessionToken()).toBeNull()
    expect(sessionStorage.getItem('uptimex.preview-session.v1')).toBeNull()
  })

  it('clears expired or rejected preview credentials', async () => {
    const { storePreviewSession, getPreviewSessionToken } = await import('./previewSession')
    storePreviewSession({ ...previewSession, expires_at: '2020-01-01T00:00:00Z' })
    expect(getPreviewSessionToken()).toBeNull()
    storePreviewSession(previewSession)
    respond({ error: { message: 'Expired' } }, 401)
    await api.me().catch(() => {})
    expect(getPreviewSessionToken()).toBeNull()
  })
})
