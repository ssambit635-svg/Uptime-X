import { lazy, Suspense, useEffect, useState } from 'react'
import { Activity, Play, RefreshCw } from 'lucide-react'

import { api, errorMessage } from '../lib/api'
import type { Analytics, AnalyticsWindow, CheckList, Monitor } from '../lib/api'
import { Modal } from './Modal'
import { ms, percent, timestamp } from '../lib/format'

const ResponseChart = lazy(() => import('./ResponseChart'))

export function MonitorDetails({
  monitor,
  onClose,
  onUpdated,
}: {
  monitor: Monitor
  onClose: () => void
  onUpdated: (item: Monitor) => void
}) {
  const [current, setCurrent] = useState(monitor)
  const [window, setWindow] = useState<AnalyticsWindow>('24h')
  const [region, setRegion] = useState('')
  const [offset, setOffset] = useState(0)
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [checks, setChecks] = useState<CheckList | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [pending, setPending] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  useEffect(() => {
    let alive = true
    const load = () =>
      Promise.all([
        api.monitor(monitor.id),
        api.analytics(monitor.id, window, region),
        api.checks(monitor.id, offset, region),
      ])
        .then(([item, stats, history]) => {
          if (alive) {
            setError('')
            setCurrent(item)
            setAnalytics(stats)
            setChecks(history)
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
  }, [monitor.id, window, region, offset, refreshKey])

  async function checkNow() {
    setPending(true)
    setError('')
    setMessage('')
    try {
      await api.checkNow(current.id)
      setMessage(
        'Check queued. Waiting for an actual worker result; this is not a success confirmation.',
      )
      setRefreshKey((key) => key + 1)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <Modal
      title={`${current.name} · measurements`}
      onClose={() => {
        onUpdated(current)
        onClose()
      }}
      className="measurement-modal"
    >
      <div className="measurement-body">
        <div className="measurement-heading">
          <div>
            <span className={`monitor-status ${current.status.toLowerCase()}`}>
              {current.status}
            </span>
            <span className="real-badge">REAL</span>
            <p>{current.status_reason}</p>
            <small>Last checked: {timestamp(current.last_checked_at)}</small>
          </div>
          <button
            className="button button-primary"
            onClick={checkNow}
            disabled={pending || current.status === 'PAUSED'}
          >
            <Play size={14} />
            {pending ? 'Queueing…' : 'Check now'}
          </button>
        </div>
        <div className="measurement-controls">
          <label>
            Time window
            <select
              value={window}
              onChange={(event) => {
                setWindow(event.target.value as AnalyticsWindow)
                setAnalytics(null)
                setChecks(null)
              }}
            >
              {(['24h', '7d', '30d', '90d'] as AnalyticsWindow[]).map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            Region
            <select
              value={region}
              onChange={(event) => {
                setAnalytics(null)
                setChecks(null)
                setRegion(event.target.value)
                setOffset(0)
              }}
            >
              <option value="">All configured regions</option>
              {current.regions.map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <button
            className="button button-secondary"
            onClick={() => setRefreshKey((key) => key + 1)}
          >
            <RefreshCw size={14} />
            Refresh measurements
          </button>
        </div>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        {message && (
          <div className="info-box" role="status">
            {message}
          </div>
        )}
        {analytics ? (
          <>
            <div className="measurement-stats">
              <Measure
                label="Observed availability"
                value={percent(analytics.availability_percent)}
                hint={`${analytics.successful_checks} / ${analytics.eligible_checks} eligible checks`}
              />
              <Measure
                label="Average / median"
                value={ms(analytics.average_ms)}
                hint={`Median ${ms(analytics.median_ms)} · ${analytics.latency_samples} HTTP samples`}
              />
              <Measure
                label="p95 response"
                value={ms(analytics.p95_ms)}
                hint="Nearest-rank percentile"
              />
              <Measure
                label="Sampling coverage"
                value={`${analytics.coverage_percent.toFixed(1)}%`}
                hint={`${analytics.observed_slots} / ${analytics.expected_slots} expected slots`}
              />
            </div>
            <p className="measurement-policy">
              {analytics.policy} Configuration revision {analytics.revision}, eligible since{' '}
              {timestamp(analytics.eligible_since)}. Inconclusive: {analytics.inconclusive_checks}.
              Sample-based downtime estimate: {Math.round(analytics.estimated_downtime_seconds)}{' '}
              seconds. Retention is operator-configured; older windows can be incomplete.
            </p>
            <section className="measurement-chart" aria-label="Response time history">
              <h3>
                <Activity size={16} />
                Measured response time <small>{window} · UTC · milliseconds</small>
              </h3>
              {analytics.latency_samples ? (
                <div
                  role="img"
                  aria-label={`Measured HTTP response time. ${analytics.latency_samples} samples, average ${ms(analytics.average_ms)}, p95 ${ms(analytics.p95_ms)}. Gaps mean no measurement.`}
                  style={{ width: '100%', height: 235 }}
                >
                  <Suspense fallback={<p>Loading chart…</p>}>
                    <ResponseChart data={analytics.trend} window={window} />
                  </Suspense>
                </div>
              ) : (
                <div className="no-chart-data">
                  No eligible HTTP timings in this window. Missing data is not zero latency.
                </div>
              )}
              <details className="trend-data">
                <summary>Accessible trend data ({analytics.trend.length} buckets)</summary>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Bucket start (UTC)</th>
                        <th>Eligible</th>
                        <th>Availability</th>
                        <th>Average</th>
                        <th>p95</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analytics.trend.map((point) => (
                        <tr key={point.start}>
                          <td>{timestamp(point.start)}</td>
                          <td>{point.eligible_checks}</td>
                          <td>{percent(point.availability_percent)}</td>
                          <td>{ms(point.average_ms)}</td>
                          <td>{ms(point.p95_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
            <section aria-label="Regional comparison">
              <h3>Regional comparison</h3>
              <div className="regional-cards">
                {current.regional_status
                  .filter((item) => !region || item.region === region)
                  .map((item) => (
                    <article key={item.region}>
                      <strong>{item.region === 'local' ? 'Local deployment' : item.region}</strong>
                      <span className={`monitor-status ${item.status.toLowerCase()}`}>
                        {item.status}
                      </span>
                      <p>{item.reason}</p>
                      <small>
                        {timestamp(item.last_checked_at)} · {ms(item.response_time_ms)}
                      </small>
                      {analytics.regions
                        .filter((stats) => stats.region === item.region)
                        .map((stats) => (
                          <p key={stats.region}>
                            Window availability {percent(stats.availability_percent)} ·{' '}
                            {stats.eligible_checks} eligible checks
                            <br />
                            Average {ms(stats.average_ms)} · median {ms(stats.median_ms)} · p95{' '}
                            {ms(stats.p95_ms)}
                          </p>
                        ))}
                    </article>
                  ))}
              </div>
            </section>
          </>
        ) : (
          !error && <p role="status">Loading real measurements…</p>
        )}
        <section className="check-history" aria-label="Check history">
          <h3>
            Check history <small>Actual observations · all configuration revisions</small>
          </h3>
          {checks && checks.items.length > 0 ? (
            <>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Measured check history"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Scheduled / observed (UTC)</th>
                      <th>Region</th>
                      <th>Outcome</th>
                      <th>HTTP</th>
                      <th>Total</th>
                      <th>Timing & evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.items.map((check) => (
                      <tr key={check.id}>
                        <td>
                          {timestamp(check.scheduled_at)}
                          <small className="cell-subtext">
                            Observed {timestamp(check.checked_at)}
                          </small>
                        </td>
                        <td>{check.region}</td>
                        <td>
                          <span
                            className={`monitor-status ${check.outcome === 'FAILURE' ? 'down' : check.outcome.toLowerCase()}`}
                          >
                            {check.outcome}
                          </span>
                        </td>
                        <td>{check.http_status ?? '—'}</td>
                        <td>{ms(check.total_ms)}</td>
                        <td>
                          <details>
                            <summary>Details</summary>
                            <dl>
                              <dt>DNS / TCP / TLS</dt>
                              <dd>
                                {ms(check.dns_ms)} / {ms(check.connect_ms)} / {ms(check.tls_ms)}
                              </dd>
                              <dt>TTFB (end-to-end)</dt>
                              <dd>{ms(check.ttfb_ms)}</dd>
                              <dt>Bytes / redirects</dt>
                              <dd>
                                {check.response_bytes} / {check.redirect_count}
                              </dd>
                              <dt>Error category</dt>
                              <dd>{check.error_category ?? 'None'}</dd>
                              <dt>Configuration revision</dt>
                              <dd>{check.revision}</dd>
                              <dt>Provenance</dt>
                              <dd>REAL</dd>
                            </dl>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="history-pagination">
                <button
                  className="button button-secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 50))}
                >
                  Newer checks
                </button>
                <span>
                  {offset + 1}–{Math.min(offset + checks.items.length, checks.total)} of{' '}
                  {checks.total}
                </span>
                <button
                  className="button button-secondary"
                  disabled={offset + 50 >= checks.total}
                  onClick={() => setOffset(offset + 50)}
                >
                  Older checks
                </button>
              </div>
            </>
          ) : (
            checks && (
              <p>
                No observations yet. Start the scheduler and worker, or request a check; no target
                health is assumed.
              </p>
            )
          )}
        </section>
      </div>
    </Modal>
  )
}

function Measure({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <article>
      <small>{label}</small>
      <strong>{value}</strong>
      <span>{hint}</span>
    </article>
  )
}
