import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../lib/api'
import { analytics, check, monitor } from '../test/monitoringFixtures'
import { MonitorDetails } from './MonitorDetails'

vi.mock('./ResponseChart', () => ({ default: () => <div>Measured chart</div> }))

beforeEach(() => {
  vi.spyOn(api, 'monitor').mockResolvedValue(monitor)
  vi.spyOn(api, 'analytics').mockResolvedValue(analytics)
  vi.spyOn(api, 'checks').mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
})

function open() {
  const onUpdated = vi.fn()
  const onClose = vi.fn()
  render(<MonitorDetails monitor={monitor} onUpdated={onUpdated} onClose={onClose} />)
  return { onUpdated, onClose }
}

describe('real measurements', () => {
  it('never turns absent observations into uptime or zero-latency evidence', async () => {
    open()
    expect(await screen.findByText(/No eligible HTTP timings/)).toBeInTheDocument()
    expect(screen.getByText(/No observations yet/)).toBeInTheDocument()
    expect(screen.queryByText('100.00%')).not.toBeInTheDocument()
    expect(screen.queryByText('0.0 ms')).not.toBeInTheDocument()
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
    expect(screen.getByText('REAL')).toBeInTheDocument()
  })

  it('renders measured timing/evidence, chart summary and accessible bucket table', async () => {
    const user = userEvent.setup()
    vi.mocked(api.analytics).mockResolvedValue({
      ...analytics,
      samples: 1,
      eligible_checks: 1,
      successful_checks: 1,
      availability_percent: 100,
      latency_samples: 1,
      average_ms: 42,
      median_ms: 42,
      p95_ms: 42,
      observed_slots: 1,
      coverage_percent: 100,
    })
    vi.mocked(api.checks).mockResolvedValue({ items: [check], total: 1, limit: 50, offset: 0 })
    open()
    expect(
      await screen.findByRole('img', { name: /1 samples, average 42.0 ms/ }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Measured chart')).toBeInTheDocument()
    await user.click(screen.getByText(/Accessible trend data/))
    expect(screen.getByRole('columnheader', { name: 'Bucket start (UTC)' })).toBeVisible()
    const history = screen.getByRole('region', { name: 'Measured check history' })
    expect(within(history).getByText('200')).toBeInTheDocument()
    await user.click(within(history).getByText('Details'))
    expect(within(history).getByText('1.0 ms / 2.0 ms / 3.0 ms')).toBeVisible()
    expect(within(history).getByText('REAL')).toBeVisible()
  })

  it('queues explicitly without claiming a successful target check', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'checkNow').mockResolvedValue({ state: 'QUEUED', job_ids: ['job-one'] })
    open()
    await user.click(screen.getByRole('button', { name: 'Check now' }))
    expect(await screen.findByRole('status')).toHaveTextContent('not a success confirmation')
    expect(api.checkNow).toHaveBeenCalledWith('monitor-one')
    expect(screen.getAllByText('UNKNOWN')).toHaveLength(2)
    expect(screen.queryByText('UP', { exact: true })).not.toBeInTheDocument()
  })

  it('shows worker/API errors and allows a measured refresh', async () => {
    const user = userEvent.setup()
    vi.mocked(api.analytics).mockRejectedValueOnce(new Error('Measurements unavailable.'))
    open()
    expect(await screen.findByRole('alert')).toHaveTextContent('Measurements unavailable.')
    await user.click(screen.getByRole('button', { name: 'Refresh measurements' }))
    expect(await screen.findByText(/No eligible HTTP timings/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('applies region/window filters and bounded history pagination', async () => {
    const user = userEvent.setup()
    vi.mocked(api.checks).mockResolvedValue({ items: [check], total: 51, limit: 50, offset: 0 })
    open()
    await screen.findByText(/No eligible HTTP timings/)
    await user.selectOptions(screen.getByLabelText('Time window'), '7d')
    await waitFor(() => expect(api.analytics).toHaveBeenLastCalledWith('monitor-one', '7d', ''))
    await user.selectOptions(screen.getByLabelText('Region'), 'local')
    await waitFor(() =>
      expect(api.analytics).toHaveBeenLastCalledWith('monitor-one', '7d', 'local'),
    )
    await user.click(screen.getByRole('button', { name: 'Older checks' }))
    await waitFor(() => expect(api.checks).toHaveBeenLastCalledWith('monitor-one', 50, 'local'))
    await user.click(screen.getByRole('button', { name: 'Newer checks' }))
    await waitFor(() => expect(api.checks).toHaveBeenLastCalledWith('monitor-one', 0, 'local'))
  })

  it('retains rate-limit errors and updates the parent on a native dialog cancel', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'checkNow').mockRejectedValue(new Error('Wait one minute.'))
    const { onUpdated, onClose } = open()
    await user.click(screen.getByRole('button', { name: 'Check now' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wait one minute.')
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(onUpdated).toHaveBeenCalledWith(monitor)
    expect(onClose).toHaveBeenCalledOnce()
  })
})
