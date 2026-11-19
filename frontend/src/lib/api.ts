import { clearPreviewSession, getPreviewSessionToken, storePreviewSession } from './previewSession'
import type { PreviewSession } from './previewSession'

export interface User {
  id: string
  email: string
  created_at: string
}

interface AuthResponse extends User {
  preview_session?: PreviewSession
}

export interface Monitor {
  id: string
  name: string
  target_url: string
  interval_seconds: number
  timeout_seconds: number
  status: 'UNKNOWN' | 'PAUSED'
  provenance: 'REAL'
  created_at: string
  updated_at: string
  last_checked_at: null
  availability_percent: null
  response_time_ms: null
}

export interface MonitorInput {
  name: string
  target_url: string
  interval_seconds: number
  timeout_seconds: number
}

export interface MonitorList {
  items: Monitor[]
  total: number
  quota: number
  checks_enabled: false
}

export class ApiError extends Error {
  status: number
  code: string
  constructor(message: string, status: number, code: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response
  const previewToken = getPreviewSessionToken()
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      credentials: 'same-origin',
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        'X-UptimeX-Client': 'web',
        ...(previewToken ? { 'X-UptimeX-Preview-Session': previewToken } : {}),
        ...options.headers,
      },
      signal: options.signal ?? AbortSignal.timeout(15_000),
    })
  } catch {
    throw new ApiError(
      'Could not reach UptimeX. Check your connection and try again.',
      0,
      'NETWORK_ERROR',
    )
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    if (response.status === 401 && !['/auth/login', '/auth/register'].includes(path)) {
      clearPreviewSession()
    }
    if (response.status === 401 && !['/auth/me', '/auth/login', '/auth/register'].includes(path)) {
      window.dispatchEvent(new Event('uptimex:session-expired'))
    }
    const error = payload?.error
    const message = error?.fields?.[0]
      ? `${error.fields[0].field.replaceAll('_', ' ')}: ${error.fields[0].message}`
      : error?.message || 'Something went wrong. Please try again.'
    throw new ApiError(message, response.status, error?.code || 'REQUEST_FAILED')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  me: () => request<User>('/auth/me'),
  authenticate: async (mode: 'login' | 'register', email: string, password: string) => {
    const result = await request<AuthResponse>(`/auth/${mode}`, {
      method: 'POST',
      headers: { 'X-UptimeX-Session-Mode': 'preview' },
      body: JSON.stringify({ email, password }),
    })
    if (result.preview_session) storePreviewSession(result.preview_session)
    else clearPreviewSession()
    // Do not show an authenticated dashboard until a protected request succeeds.
    // A 200 login alone does not prove that a browser accepted its session cookie.
    try {
      return await request<User>('/auth/me')
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        throw new ApiError(
          mode === 'register'
            ? 'Your account was created, but this browser blocked the sign-in session. Open the preview in a new tab, then sign in.'
            : 'This browser blocked the sign-in session. Open the preview in a new tab and try again.',
          401,
          'SESSION_NOT_ESTABLISHED',
        )
      }
      throw error
    }
  },
  logout: async () => {
    await request<void>('/auth/logout', { method: 'POST' })
    clearPreviewSession()
  },
  monitors: () => request<MonitorList>('/monitors?limit=100'),
  createMonitor: (data: MonitorInput) =>
    request<Monitor>('/monitors', { method: 'POST', body: JSON.stringify(data) }),
  updateMonitor: (id: string, data: MonitorInput) =>
    request<Monitor>(`/monitors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  setPaused: (id: string, paused: boolean) =>
    request<Monitor>(`/monitors/${id}/${paused ? 'pause' : 'resume'}`, { method: 'POST' }),
  deleteMonitor: (id: string) => request<void>(`/monitors/${id}`, { method: 'DELETE' }),
  health: () => request<{ status: string; database: string; checks_enabled: false }>('/health'),
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
