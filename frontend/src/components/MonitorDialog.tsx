import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, Globe2, Info, LockKeyhole, ShieldCheck } from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import type { Monitor, MonitorInput } from '../lib/api'
import { Modal } from './Modal'

export function MonitorDialog({
  monitor,
  onClose,
  onSaved,
}: {
  monitor?: Monitor
  onClose: () => void
  onSaved: (monitor: Monitor) => void
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [regions, setRegions] = useState<string[]>([])
  const [selected, setSelected] = useState<string[]>(monitor?.regions ?? [])
  useEffect(() => {
    let alive = true
    api
      .operations()
      .then((result) => {
        if (alive) {
          setRegions(result.configured_regions)
          if (!monitor) setSelected(result.configured_regions)
        }
      })
      .catch(() => {
        /* Server defaults are used if capability discovery is unavailable. */
      })
    return () => {
      alive = false
    }
  }, [monitor])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const input: MonitorInput = {
      name: String(data.get('name')).trim(),
      target_url: String(data.get('target_url')).trim(),
      interval_seconds: Number(data.get('interval_seconds')),
      timeout_seconds: Number(data.get('timeout_seconds')),
      expected_status_min: Number(data.get('expected_status_min')),
      expected_status_max: Number(data.get('expected_status_max')),
      slow_threshold_ms: Number(data.get('slow_threshold_ms')),
      failure_threshold: Number(data.get('failure_threshold')),
      recovery_threshold: Number(data.get('recovery_threshold')),
      ...(selected.length ? { regions: selected } : {}),
    }
    if (regions.length && !selected.length) {
      setError('Choose at least one worker region.')
      return
    }
    if (!input.name) {
      setError('Give your monitor a name.')
      return
    }
    setPending(true)
    setError('')
    try {
      onSaved(monitor ? await api.updateMonitor(monitor.id, input) : await api.createMonitor(input))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <Modal
      title={monitor ? 'Edit website monitor' : 'Add a website'}
      onClose={onClose}
      busy={pending}
    >
      <div className="dialog-intro">
        <span className="dialog-icon">
          <Globe2 size={23} />
        </span>
        <p>
          {monitor
            ? 'Fine-tune this monitor’s configuration.'
            : 'Keep your public endpoints in one clear view.'}
          <br />
          <span>Only monitor websites you own or have permission to monitor.</span>
        </p>
      </div>
      <form onSubmit={submit} className="monitor-form">
        <label htmlFor="monitor-name">Monitor name</label>
        <input
          id="monitor-name"
          name="name"
          placeholder="e.g. Production website"
          maxLength={120}
          defaultValue={monitor?.name}
          required
          disabled={pending}
        />
        <label htmlFor="monitor-url">
          Website URL <span className="field-tag">HTTP / HTTPS</span>
        </label>
        <input
          id="monitor-url"
          name="target_url"
          type="url"
          placeholder="https://your-website.com"
          maxLength={2048}
          defaultValue={monitor?.target_url}
          required
          disabled={pending}
          aria-describedby="url-hint"
        />
        <small id="url-hint">
          <LockKeyhole size={12} /> Public addresses only. Private networks are blocked.
        </small>
        <div className="form-columns">
          <div>
            <label htmlFor="monitor-interval">Check interval</label>
            <select
              id="monitor-interval"
              name="interval_seconds"
              defaultValue={monitor?.interval_seconds ?? 300}
              disabled={pending}
            >
              <option value="300">Every 5 minutes</option>
              <option value="600">Every 10 minutes</option>
              <option value="900">Every 15 minutes</option>
              <option value="1800">Every 30 minutes</option>
              <option value="3600">Every 60 minutes</option>
            </select>
          </div>
          <div>
            <label htmlFor="monitor-timeout">Request timeout</label>
            <select
              id="monitor-timeout"
              name="timeout_seconds"
              defaultValue={monitor?.timeout_seconds ?? 10}
              disabled={pending}
            >
              <option value="5">5 seconds</option>
              <option value="10">10 seconds</option>
              {monitor && ![5, 10].includes(monitor.timeout_seconds) && (
                <option value={monitor.timeout_seconds}>{monitor.timeout_seconds} seconds</option>
              )}
            </select>
          </div>
        </div>
        <details className="policy-fields">
          <summary>Response policy & worker regions</summary>
          <div className="form-columns">
            <div>
              <label htmlFor="status-min">Expected HTTP minimum</label>
              <input
                id="status-min"
                name="expected_status_min"
                type="number"
                min="100"
                max="599"
                required
                defaultValue={monitor?.expected_status_min ?? 200}
                disabled={pending}
              />
            </div>
            <div>
              <label htmlFor="status-max">Expected HTTP maximum</label>
              <input
                id="status-max"
                name="expected_status_max"
                type="number"
                min="100"
                max="599"
                required
                defaultValue={monitor?.expected_status_max ?? 299}
                disabled={pending}
              />
            </div>
          </div>
          <div className="form-columns">
            <div>
              <label htmlFor="slow-ms">Slow response threshold (ms)</label>
              <input
                id="slow-ms"
                name="slow_threshold_ms"
                type="number"
                min="100"
                max="10000"
                required
                defaultValue={monitor?.slow_threshold_ms ?? 2000}
                disabled={pending}
              />
            </div>
            <div>
              <label htmlFor="fail-threshold">Failures before DOWN</label>
              <input
                id="fail-threshold"
                name="failure_threshold"
                type="number"
                min="2"
                max="10"
                required
                defaultValue={monitor?.failure_threshold ?? 3}
                disabled={pending}
              />
            </div>
          </div>
          <label htmlFor="recover-threshold">Successes to recover</label>
          <input
            id="recover-threshold"
            name="recovery_threshold"
            type="number"
            min="1"
            max="10"
            required
            defaultValue={monitor?.recovery_threshold ?? 2}
            disabled={pending}
          />
          <fieldset>
            <legend>Worker regions</legend>
            {regions.length ? (
              regions.map((region) => (
                <label className="region-choice" key={region}>
                  <input
                    type="checkbox"
                    checked={selected.includes(region)}
                    onChange={(event) =>
                      setSelected(
                        event.target.checked
                          ? [...selected, region]
                          : selected.filter((r) => r !== region),
                      )
                    }
                    disabled={pending}
                  />
                  {region === 'local' ? 'Local deployment (not an AWS region)' : region}
                </label>
              ))
            ) : (
              <small>
                Using server-configured regions. Region capabilities could not be loaded yet.
              </small>
            )}
          </fieldset>
        </details>
        <div className="info-box">
          <Info size={17} />
          <p>
            <strong>Real checks. No invented uptime.</strong> Public DNS and every
            connection/redirect are revalidated. Status stays UNKNOWN until a worker records a fresh
            observation. Missing data is never counted as success.
          </p>
        </div>
        {error && (
          <div className="form-error" role="alert">
            {error}
          </div>
        )}
        <div className="modal-footer">
          <span>
            <ShieldCheck size={14} /> Safely validated
          </span>
          <button
            type="button"
            className="button button-secondary"
            onClick={onClose}
            disabled={pending}
          >
            Cancel
          </button>
          <button className="button button-primary" type="submit" disabled={pending}>
            {pending ? 'Validating…' : monitor ? 'Save changes' : 'Add website'}
            {!pending && <ArrowRight size={15} />}
          </button>
        </div>
      </form>
    </Modal>
  )
}
