import { useEffect, useState } from 'react'
import { Info, RefreshCw } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import type { Monitor, Operations } from '../lib/api'
import { ms, percent, timestamp } from '../lib/format'

export function FleetHealth({
  monitors,
  onSelect,
  analytics = false,
}: {
  monitors: Monitor[]
  onSelect: (monitor: Monitor) => void
  analytics?: boolean
}) {
  const [ops, setOps] = useState<Operations | null>(null)
  const [error, setError] = useState('')
  const [version, setVersion] = useState(0)
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .operations()
        .then((result) => {
          if (alive) {
            setOps(result)
            setError('')
          }
        })
        .catch((err: unknown) => {
          if (alive) setError(errorMessage(err))
        })
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 15_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [version])
  return (
    <section
      className="panel fleet-health"
      aria-label={analytics ? 'Fleet analytics' : 'Regional worker health'}
    >
      <div className="panel-heading">
        <div>
          <h2>
            {analytics ? 'Measured website performance' : 'Regional monitoring & pipeline health'}
          </h2>
          <p>REAL observations only. Local processes are never presented as AWS regions.</p>
        </div>
        <button
          className="button button-secondary"
          onClick={() => setVersion((value) => value + 1)}
        >
          <RefreshCw size={14} />
          Refresh health
        </button>
      </div>
      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}
      {ops ? (
        <>
          <div className="pipeline-summary">
            <div>
              <small>Engine</small>
              <strong>{ops.checks_enabled ? 'Enabled' : 'Disabled'}</strong>
              <span>
                {ops.queue_transport === 'sqs'
                  ? 'AWS SQS transport configured'
                  : 'Durable local database queue'}
              </span>
            </div>
            <div>
              <small>Scheduler</small>
              <strong>
                {ops.scheduler.healthy ? 'Heartbeat recent' : 'UNKNOWN / not reporting'}
              </strong>
              <span>{timestamp(ops.scheduler.last_seen_at)}</span>
            </div>
            <div>
              <small>Your queued / dead jobs</small>
              <strong>
                {ops.jobs.pending} / {ops.jobs.dead}
              </strong>
              <span>
                Oldest pending:{' '}
                {ops.jobs.oldest_pending_seconds === null
                  ? 'none'
                  : `${Math.round(ops.jobs.oldest_pending_seconds)} seconds`}
              </span>
            </div>
          </div>
          <div className="regional-cards">
            {ops.regions.map((region) => (
              <article key={region.region}>
                <strong>{region.region === 'local' ? 'Local deployment' : region.region}</strong>
                <span className={`monitor-status ${region.healthy_workers ? 'up' : 'unknown'}`}>
                  {region.healthy_workers ? 'HEARTBEAT RECENT' : 'UNKNOWN'}
                </span>
                <p>{region.healthy_workers} workers reporting within 90 seconds</p>
                <small>Last seen: {timestamp(region.last_seen_at)}</small>
              </article>
            ))}
          </div>
          {(!ops.scheduler.healthy ||
            ops.regions.some((region) => !region.healthy_workers) ||
            ops.jobs.dead > 0) && (
            <div className="info-box">
              <Info size={17} />
              <p>
                Monitoring coverage may be incomplete. Check scheduler/worker logs, queue age and
                dead-letter jobs. Missing observations never improve availability.
              </p>
            </div>
          )}
        </>
      ) : (
        !error && (
          <p className="fleet-loading" role="status">
            Loading observed pipeline health…
          </p>
        )
      )}
      <div
        className="table-scroll"
        tabIndex={0}
        role="region"
        aria-label="Regional website observations"
      >
        <table>
          <thead>
            <tr>
              <th>Website</th>
              <th>Status</th>
              <th>Availability (24h)</th>
              <th>Last response</th>
              <th>Regional evidence</th>
            </tr>
          </thead>
          <tbody>
            {monitors.map((monitor) => (
              <tr key={monitor.id}>
                <td>
                  <button className="measurement-link" onClick={() => onSelect(monitor)}>
                    {monitor.name}
                  </button>
                </td>
                <td>
                  <span className={`monitor-status ${monitor.status.toLowerCase()}`}>
                    {monitor.status}
                  </span>
                </td>
                <td>
                  {percent(monitor.availability_percent)}
                  <small className="cell-subtext">{monitor.eligible_checks} eligible samples</small>
                </td>
                <td>
                  {ms(monitor.response_time_ms)}
                  <small className="cell-subtext">{timestamp(monitor.last_checked_at)}</small>
                </td>
                <td>
                  {monitor.regional_status.map((item) => (
                    <div className="region-evidence" key={item.region}>
                      <span>{item.region}</span>
                      <span className={`monitor-status ${item.status.toLowerCase()}`}>
                        {item.status}
                      </span>
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!monitors.length && (
          <p className="fleet-loading">
            Add a website to collect measurements. There are no sample websites or fabricated
            regional signals.
          </p>
        )}
      </div>
    </section>
  )
}
