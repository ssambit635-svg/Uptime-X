import { useState } from 'react'
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    const input: MonitorInput = {
      name: String(data.get('name')).trim(),
      target_url: String(data.get('target_url')).trim(),
      interval_seconds: Number(data.get('interval_seconds')),
      timeout_seconds: Number(data.get('timeout_seconds')),
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
        <div className="info-box">
          <Info size={17} />
          <p>
            <strong>Configuration now. Real checks next.</strong>This release saves your monitor.
            Status stays UNKNOWN until the check engine is connected. No requests are sent to your
            website yet.
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
