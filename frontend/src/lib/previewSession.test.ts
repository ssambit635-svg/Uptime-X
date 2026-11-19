import { beforeEach, describe, expect, it, vi } from 'vitest'

const key = 'uptimex.preview-session.v1'
const session = {
  token: 'B'.repeat(43),
  expires_at: new Date(Date.now() + 3_600_000).toISOString(),
}

beforeEach(() => {
  vi.resetModules()
  sessionStorage.clear()
})

describe('tab-scoped preview credentials', () => {
  it('restores an unexpired credential after reloading the module', async () => {
    sessionStorage.setItem(key, JSON.stringify(session))
    const { getPreviewSessionToken } = await import('./previewSession')
    expect(getPreviewSessionToken()).toBe(session.token)
  })

  it.each([
    'not-json',
    'null',
    JSON.stringify({ token: 'short', expires_at: session.expires_at }),
    JSON.stringify({ ...session, expires_at: '2020-01-01T00:00:00Z' }),
  ])('discards malformed or expired stored credentials (%s)', async (raw) => {
    sessionStorage.setItem(key, raw)
    const { getPreviewSessionToken } = await import('./previewSession')
    expect(getPreviewSessionToken()).toBeNull()
    expect(sessionStorage.getItem(key)).toBeNull()
  })

  it('removes the memory and stored credential when it expires', async () => {
    const { storePreviewSession, getPreviewSessionToken } = await import('./previewSession')
    storePreviewSession(session)
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse(session.expires_at) + 1)
    expect(getPreviewSessionToken()).toBeNull()
    expect(sessionStorage.getItem(key)).toBeNull()
  })

  it('works in memory when the browser rejects every storage operation', async () => {
    for (const operation of ['getItem', 'setItem', 'removeItem'] as const) {
      vi.spyOn(Storage.prototype, operation).mockImplementation(() => {
        throw new DOMException('Denied', 'SecurityError')
      })
    }
    const { storePreviewSession, getPreviewSessionToken, clearPreviewSession } =
      await import('./previewSession')
    expect(getPreviewSessionToken()).toBeNull()
    storePreviewSession(session)
    expect(getPreviewSessionToken()).toBe(session.token)
    clearPreviewSession()
    expect(getPreviewSessionToken()).toBeNull()
  })
})
