// Development-preview transport only. Production never issues this credential.
// Use tab-scoped sessionStorage (not localStorage), with a memory-only fallback
// when the browser denies storage. The server enforces expiry and revocation.
export interface PreviewSession {
  token: string
  expires_at: string
}

const STORAGE_KEY = 'uptimex.preview-session.v1'
let memorySession: PreviewSession | null = null
let storageRead = false

function validSession(value: unknown): value is PreviewSession {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<PreviewSession>
  return (
    typeof candidate.token === 'string' &&
    /^[A-Za-z0-9_-]{43}$/.test(candidate.token) &&
    typeof candidate.expires_at === 'string' &&
    Number.isFinite(Date.parse(candidate.expires_at)) &&
    Date.parse(candidate.expires_at) > Date.now()
  )
}

export function clearPreviewSession(): void {
  memorySession = null
  storageRead = true
  try {
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Some embedded/private contexts disable storage entirely.
  }
}

export function storePreviewSession(session: PreviewSession): void {
  clearPreviewSession()
  if (!validSession(session)) return
  memorySession = { token: session.token, expires_at: session.expires_at }
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(memorySession))
  } catch {
    // Sign-in still works for this page lifetime; a reload will require sign-in.
  }
}

export function getPreviewSessionToken(): string | null {
  if (!storageRead) {
    storageRead = true
    try {
      const saved: unknown = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || 'null')
      if (validSession(saved)) memorySession = saved
      else clearPreviewSession()
    } catch {
      // Malformed/unavailable storage must not prevent opening the sign-in screen.
      clearPreviewSession()
    }
  }
  if (memorySession && !validSession(memorySession)) clearPreviewSession()
  return memorySession?.token ?? null
}
