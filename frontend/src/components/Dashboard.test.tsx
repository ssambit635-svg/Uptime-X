import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { Monitor } from '../lib/api'
import { Dashboard } from './Dashboard'

const user = { id: 'u1', email: 'owner@example.com', created_at: '2026-11-19T00:00:00Z' }
const monitor: Monitor = {
  id: 'm1',
  name: 'Production',
  target_url: 'https://example.com/',
  interval_seconds: 300,
  timeout_seconds: 10,
  expected_status_min: 200,
  expected_status_max: 299,
  slow_threshold_ms: 2000,
  failure_threshold: 3,
  recovery_threshold: 2,
  regions: ['local'],
  revision: 1,
  revision_started_at: '2026-11-19T00:00:00Z',
  status_reason: 'No trustworthy observation yet.',
  eligible_checks: 0,
  regional_status: [],

  status: 'UNKNOWN',
  provenance: 'REAL',
  created_at: user.created_at,
  updated_at: user.created_at,
  last_checked_at: null,
  availability_percent: null,
  response_time_ms: null,
}
function setup(items: Monitor[] = []) {
  window.location.hash = ''
  vi.spyOn(api, 'monitors').mockResolvedValue({
    items,
    total: items.length,
    quota: 10,
    checks_enabled: false,
  })
  vi.spyOn(api, 'health').mockResolvedValue({
    status: 'ok',
    database: 'connected',
    checks_enabled: false,
  })
  return render(<Dashboard user={user} onLogout={vi.fn()} />)
}

describe('honest dashboard states', () => {
  it('shows an empty workspace, never invented uptime', async () => {
    setup()
    expect(await screen.findByText('A home for your first website.')).toBeInTheDocument()
    expect(screen.queryByText(/99\.9|100%|0%/)).not.toBeInTheDocument()
    expect(screen.getByText(/Incidents and alerts are not active yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Incidents/ })).toBeDisabled()
  })
  it('displays UNKNOWN and unmeasured values for a newly configured monitor', async () => {
    setup([monitor])
    expect(await screen.findByText('UNKNOWN', { exact: true })).toBeInTheDocument()
    expect(screen.getByText('No check data')).toBeInTheDocument()
    expect(screen.getByText('Not measured')).toBeInTheDocument()
    expect(screen.queryByText(/100%|\d+ ms/)).not.toBeInTheDocument()
  })
  it('can pause a monitor using the backend and filter the result', async () => {
    const interaction = userEvent.setup()
    vi.spyOn(api, 'setPaused').mockResolvedValue({ ...monitor, status: 'PAUSED' })
    setup([monitor])
    await interaction.click(await screen.findByRole('button', { name: 'Pause Production' }))
    expect(await screen.findByText('PAUSED', { exact: true })).toBeInTheDocument()
    expect(api.setPaused).toHaveBeenCalledWith('m1', true)
    await interaction.click(screen.getByRole('button', { name: /Awaiting/ }))
    expect(await screen.findByText('No websites match.')).toBeInTheDocument()
  })
  it('requires confirmation before deletion', async () => {
    const interaction = userEvent.setup()
    const remove = vi.spyOn(api, 'deleteMonitor').mockResolvedValue()
    setup([monitor])
    await interaction.click(await screen.findByRole('button', { name: 'Delete Production' }))
    expect(remove).not.toHaveBeenCalled()
    await interaction.click(screen.getByRole('button', { name: 'Delete monitor' }))
    expect(await screen.findByText('A home for your first website.')).toBeInTheDocument()
    expect(remove).toHaveBeenCalledWith('m1')
  })
  it('does not confuse a failed list request with zero monitors', async () => {
    setup()
    vi.mocked(api.monitors).mockRejectedValueOnce(new Error('Connection interrupted.'))
    // The initial call already started; test the explicit refresh failure.
    await screen.findByText('A home for your first website.')
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted.')
  })
})
