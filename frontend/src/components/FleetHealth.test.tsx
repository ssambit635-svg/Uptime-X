import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { monitor, operations } from '../test/monitoringFixtures'
import { FleetHealth } from './FleetHealth'

describe('measured fleet health', () => {
  it('labels local deployment honestly, surfaces missing heartbeats and tenant dead jobs', async () => {
    vi.spyOn(api, 'operations').mockResolvedValue(operations)
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<FleetHealth monitors={[monitor]} onSelect={onSelect} />)
    expect(await screen.findByText('Durable local database queue')).toBeInTheDocument()
    expect(screen.getByText('Local deployment')).toBeInTheDocument()
    expect(screen.getByText('UNKNOWN / not reporting')).toBeInTheDocument()
    expect(screen.getByText('2 / 1')).toBeInTheDocument()
    expect(screen.getByText(/Monitoring coverage may be incomplete/)).toBeInTheDocument()
    expect(screen.queryByText('AWS SQS transport configured')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Owned website' }))
    expect(onSelect).toHaveBeenCalledWith(monitor)
  })

  it('does not invent regional evidence for an empty account', async () => {
    vi.spyOn(api, 'operations').mockResolvedValue({
      ...operations,
      queue_transport: 'sqs',
      configured_regions: ['ap-south-1'],
      scheduler: { healthy: true, last_seen_at: '2026-11-19T12:00:00Z' },
      regions: [{ region: 'ap-south-1', healthy_workers: 1, last_seen_at: '2026-11-19T12:00:00Z' }],
      jobs: { pending: 0, dead: 0, oldest_pending_seconds: null },
    })
    render(<FleetHealth monitors={[]} onSelect={vi.fn()} analytics />)
    expect(await screen.findByText('AWS SQS transport configured')).toBeInTheDocument()
    expect(screen.getByText('ap-south-1')).toBeInTheDocument()
    expect(
      screen.getByText(/no sample websites or fabricated regional signals/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Monitoring coverage may be incomplete/)).not.toBeInTheDocument()
  })

  it('reports a health request failure and retries without fabricating status', async () => {
    const user = userEvent.setup()
    const request = vi
      .spyOn(api, 'operations')
      .mockRejectedValueOnce(new Error('Health unavailable.'))
    render(<FleetHealth monitors={[]} onSelect={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Health unavailable.')
    expect(screen.queryByText('Heartbeat recent')).not.toBeInTheDocument()
    request.mockResolvedValue(operations)
    await user.click(screen.getByRole('button', { name: 'Refresh health' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(screen.getByText('UNKNOWN / not reporting')).toBeInTheDocument()
  })
})
