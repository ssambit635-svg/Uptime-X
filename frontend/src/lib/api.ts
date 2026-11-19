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
  status: 'UP' | 'DEGRADED' | 'DOWN' | 'UNKNOWN' | 'PAUSED'
  provenance: 'REAL'
  created_at: string
  updated_at: string
  expected_status_min: number
  expected_status_max: number
  slow_threshold_ms: number
  failure_threshold: number
  recovery_threshold: number
  regions: string[]
  revision: number
  revision_started_at: string
  status_reason: string
  eligible_checks: number
  regional_status: RegionalStatus[]
  last_checked_at: string | null
  availability_percent: number | null
  response_time_ms: number | null
}

export interface MonitorInput {
  name: string
  target_url: string
  interval_seconds: number
  timeout_seconds: number
  expected_status_min: number
  expected_status_max: number
  slow_threshold_ms: number
  failure_threshold: number
  recovery_threshold: number
  regions?: string[]
}

export interface RegionalStatus {
  region: string
  status: Monitor['status']
  reason: string
  last_checked_at: string | null
  response_time_ms: number | null
}

export interface Check {
  id: string
  job_id: string
  revision: number
  region: string
  scheduled_at: string
  started_at: string
  checked_at: string
  outcome: 'UP' | 'DEGRADED' | 'FAILURE' | 'UNKNOWN'
  http_status: number | null
  dns_ms: number | null
  connect_ms: number | null
  tls_ms: number | null
  ttfb_ms: number | null
  total_ms: number
  response_bytes: number
  redirect_count: number
  error_category: string | null
  provenance: 'REAL'
}

export interface CheckList {
  items: Check[]
  total: number
  limit: number
  offset: number
}
export interface SampleStats {
  samples: number
  eligible_checks: number
  successful_checks: number
  failed_checks: number
  inconclusive_checks: number
  availability_percent: number | null
  latency_samples: number
  average_ms: number | null
  median_ms: number | null
  p95_ms: number | null
}
export type AnalyticsWindow = '24h' | '7d' | '30d' | '90d'
export interface Analytics extends SampleStats {
  window: AnalyticsWindow
  start: string
  end: string
  eligible_since: string
  revision: number
  expected_slots: number
  observed_slots: number
  coverage_percent: number
  estimated_downtime_seconds: number
  policy: string
  regions: (SampleStats & { region: string })[]
  trend: (SampleStats & { start: string; end: string })[]
  provenance: 'REAL'
}
export interface Operations {
  checks_enabled: boolean
  queue_transport: 'database' | 'sqs'
  configured_regions: string[]
  retention_days: number
  scheduler: { last_seen_at: string | null; healthy: boolean }
  regions: { region: string; healthy_workers: number; last_seen_at: string | null }[]
  jobs: { pending: number; dead: number; oldest_pending_seconds: number | null }
}

export interface MonitorList {
  items: Monitor[]
  total: number
  quota: number
  checks_enabled: boolean
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
  monitor: (id: string) => request<Monitor>(`/monitors/${id}`),
  checks: (id: string, offset = 0, region = '') =>
    request<CheckList>(
      `/monitors/${id}/checks?limit=50&offset=${offset}${region ? `&region=${encodeURIComponent(region)}` : ''}`,
    ),
  analytics: (id: string, window: AnalyticsWindow = '24h', region = '') =>
    request<Analytics>(
      `/monitors/${id}/analytics?window=${window}${region ? `&region=${encodeURIComponent(region)}` : ''}`,
    ),
  checkNow: (id: string) =>
    request<{ job_ids: string[]; state: string }>(`/monitors/${id}/check`, { method: 'POST' }),
  operations: () => request<Operations>('/operations'),
  createMonitor: (data: MonitorInput) =>
    request<Monitor>('/monitors', { method: 'POST', body: JSON.stringify(data) }),
  updateMonitor: (id: string, data: MonitorInput) =>
    request<Monitor>(`/monitors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  setPaused: (id: string, paused: boolean) =>
    request<Monitor>(`/monitors/${id}/${paused ? 'pause' : 'resume'}`, { method: 'POST' }),
  deleteMonitor: (id: string) => request<void>(`/monitors/${id}`, { method: 'DELETE' }),
  health: () => request<{ status: string; database: string; checks_enabled: boolean }>('/health'),
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
