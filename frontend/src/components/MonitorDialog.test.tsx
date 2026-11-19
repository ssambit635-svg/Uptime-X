import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import type { Monitor } from '../lib/api'
import { MonitorDialog } from './MonitorDialog'
import { operations } from '../test/monitoringFixtures'

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
  created_at: '2026-11-19T00:00:00Z',
  updated_at: '2026-11-19T00:00:00Z',
  last_checked_at: null,
  availability_percent: null,
  response_time_ms: null,
}

describe('monitor configuration', () => {
  it('saves discovered regions and response policy instead of hard-coding cloud attribution', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'operations').mockResolvedValue({
      ...operations,
      configured_regions: ['ap-south-1', 'ap-southeast-1'],
    })
    vi.spyOn(api, 'createMonitor').mockResolvedValue(monitor)
    render(<MonitorDialog onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.type(screen.getByLabelText('Monitor name'), 'Regional website')
    await user.type(screen.getByLabelText(/Website URL/), 'https://example.com')
    await user.click(screen.getByText('Response policy & worker regions'))
    await user.click(await screen.findByLabelText('ap-southeast-1'))
    await user.clear(screen.getByLabelText('Expected HTTP maximum'))
    await user.type(screen.getByLabelText('Expected HTTP maximum'), '399')
    await user.click(screen.getByRole('button', { name: 'Add website' }))
    await waitFor(() =>
      expect(api.createMonitor).toHaveBeenCalledWith(
        expect.objectContaining({
          regions: ['ap-south-1'],
          expected_status_max: 399,
        }),
      ),
    )
  })
  it('does not silently select default regions after a user deselects them all', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'operations').mockResolvedValue(operations)
    const create = vi.spyOn(api, 'createMonitor')
    render(<MonitorDialog onClose={vi.fn()} onSaved={vi.fn()} />)
    await user.type(screen.getByLabelText('Monitor name'), 'Unconfigured website')
    await user.type(screen.getByLabelText(/Website URL/), 'https://example.com')
    await user.click(screen.getByText('Response policy & worker regions'))
    await user.click(await screen.findByLabelText('Local deployment (not an AWS region)'))
    await user.click(screen.getByRole('button', { name: 'Add website' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose at least one worker region.')
    expect(create).not.toHaveBeenCalled()
  })
  it('explains the release boundary and saves actual form values', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'createMonitor').mockResolvedValue(monitor)
    const saved = vi.fn()
    render(<MonitorDialog onClose={vi.fn()} onSaved={saved} />)
    expect(screen.getByText('Real checks. No invented uptime.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Monitor name'), 'Production')
    await user.type(screen.getByLabelText(/Website URL/), 'https://example.com')
    await user.selectOptions(screen.getByLabelText('Check interval'), '600')
    await user.click(screen.getByRole('button', { name: 'Add website' }))
    await waitFor(() => expect(saved).toHaveBeenCalledWith(monitor))
    expect(api.createMonitor).toHaveBeenCalledWith({
      name: 'Production',
      target_url: 'https://example.com',
      interval_seconds: 600,
      timeout_seconds: 10,
      expected_status_min: 200,
      expected_status_max: 299,
      slow_threshold_ms: 2000,
      failure_threshold: 3,
      recovery_threshold: 2,
    })
  })
  it('keeps the form open and retains input after server rejection', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'createMonitor').mockRejectedValue(new Error('Private addresses are blocked.'))
    const saved = vi.fn()
    render(<MonitorDialog onClose={vi.fn()} onSaved={saved} />)
    await user.type(screen.getByLabelText('Monitor name'), 'Private endpoint')
    await user.type(screen.getByLabelText(/Website URL/), 'http://127.0.0.1')
    await user.click(screen.getByRole('button', { name: 'Add website' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Private addresses are blocked.')
    expect(screen.getByLabelText('Monitor name')).toHaveValue('Private endpoint')
    expect(saved).not.toHaveBeenCalled()
  })
  it('edits existing configuration instead of creating another record', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'updateMonitor').mockResolvedValue({ ...monitor, name: 'Marketing' })
    const saved = vi.fn()
    render(<MonitorDialog monitor={monitor} onClose={vi.fn()} onSaved={saved} />)
    await user.clear(screen.getByLabelText('Monitor name'))
    await user.type(screen.getByLabelText('Monitor name'), 'Marketing')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    await waitFor(() =>
      expect(api.updateMonitor).toHaveBeenCalledWith(
        'm1',
        expect.objectContaining({ name: 'Marketing' }),
      ),
    )
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ name: 'Marketing' }))
  })
})
