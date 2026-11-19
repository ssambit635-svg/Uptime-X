import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  CheckCheck,
  ChevronRight,
  Clock3,
  FlaskConical,
  Globe2,
  Info,
  LayoutDashboard,
  LogOut,
  Menu,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Plus,
  Radar,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-react'
import { api, errorMessage } from '../lib/api'
import type { Monitor, MonitorList, User } from '../lib/api'
import { Brand } from './Brand'
import { Modal } from './Modal'
import { MonitorDialog } from './MonitorDialog'
import { MonitorDetails } from './MonitorDetails'
import { ms, percent, timestamp } from '../lib/format'
import { FleetHealth } from './FleetHealth'

type Page = 'overview' | 'websites' | 'global' | 'analytics'
type Filter = 'all' | 'awaiting' | 'paused'

function currentPage(): Page {
  const value = window.location.hash.slice(1)
  return ['websites', 'global', 'analytics'].includes(value) ? (value as Page) : 'overview'
}
function displayUrl(value: string) {
  const url = new URL(value)
  return `${url.host}${url.pathname === '/' ? '' : url.pathname}${url.search ? '?…' : ''}`
}

export function Dashboard({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [page, setPage] = useState<Page>(currentPage)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [data, setData] = useState<MonitorList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [apiConnected, setApiConnected] = useState<boolean | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [dialog, setDialog] = useState<'add' | 'guide' | 'settings' | null>(null)
  const [editing, setEditing] = useState<Monitor | undefined>()
  const [measuring, setMeasuring] = useState<Monitor | null>(null)
  const [deleting, setDeleting] = useState<Monitor | null>(null)
  const [actionError, setActionError] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [loggingOut, setLoggingOut] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .monitors()
      .then((result) => {
        if (alive) setData(result)
      })
      .catch((err: unknown) => {
        if (alive) setError(errorMessage(err))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    api
      .health()
      .then(() => {
        if (alive) setApiConnected(true)
      })
      .catch(() => {
        if (alive) setApiConnected(false)
      })
    const handleHash = () => {
      setPage(currentPage())
      setMobileOpen(false)
    }
    window.addEventListener('hashchange', handleHash)
    const poll = setInterval(() => {
      if (!document.hidden)
        api
          .monitors()
          .then((result) => {
            if (alive) setData(result)
          })
          .catch((err: unknown) => {
            if (alive) setError(errorMessage(err))
          })
    }, 15_000)
    return () => {
      clearInterval(poll)
      alive = false
      window.removeEventListener('hashchange', handleHash)
    }
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 4500)
    return () => clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (!mobileOpen) return
    const previous = document.activeElement as HTMLElement | null
    document.getElementById('close-navigation')?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMobileOpen(false)
    }
    window.addEventListener('keydown', escape)
    return () => {
      document.body.style.overflow = overflow
      window.removeEventListener('keydown', escape)
      previous?.focus()
    }
  }, [mobileOpen])

  async function refresh() {
    setLoading(true)
    setError('')
    try {
      setData(await api.monitors())
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
    api
      .health()
      .then(() => setApiConnected(true))
      .catch(() => setApiConnected(false))
  }

  function save(monitor: Monitor) {
    setData((previous) => {
      if (!previous) return previous
      const exists = previous.items.some((item) => item.id === monitor.id)
      return {
        ...previous,
        items: exists
          ? previous.items.map((item) => (item.id === monitor.id ? monitor : item))
          : [monitor, ...previous.items],
        total: previous.total + (exists ? 0 : 1),
      }
    })
    setToast(
      editing ? 'Monitor configuration updated.' : 'Website added. Configuration saved securely.',
    )
    setDialog(null)
    setEditing(undefined)
  }

  async function togglePause(monitor: Monitor) {
    setBusyId(monitor.id)
    setError('')
    try {
      const updated = await api.setPaused(monitor.id, monitor.status !== 'PAUSED')
      setData(
        (previous) =>
          previous && {
            ...previous,
            items: previous.items.map((item) => (item.id === updated.id ? updated : item)),
          },
      )
      setToast(
        updated.status === 'PAUSED'
          ? 'Monitor paused.'
          : 'Monitor resumed. Awaiting real check data.',
      )
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function removeMonitor() {
    if (!deleting) return
    setBusyId(deleting.id)
    setActionError('')
    try {
      await api.deleteMonitor(deleting.id)
      setData(
        (previous) =>
          previous && {
            ...previous,
            items: previous.items.filter((item) => item.id !== deleting.id),
            total: previous.total - 1,
          },
      )
      setDeleting(null)
      setToast('Monitor deleted.')
    } catch (err) {
      setActionError(errorMessage(err))
    } finally {
      setBusyId(null)
    }
  }

  async function logout() {
    setLoggingOut(true)
    try {
      await api.logout()
      onLogout()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoggingOut(false)
    }
  }

  const monitors = data?.items ?? []
  const awaiting = monitors.filter((item) => item.status === 'UNKNOWN').length
  const paused = monitors.filter((item) => item.status === 'PAUSED').length
  const filtered = monitors.filter(
    (item) =>
      (filter === 'all' ||
        (filter === 'paused' ? item.status === 'PAUSED' : item.status === 'UNKNOWN')) &&
      `${item.name} ${item.target_url}`.toLowerCase().includes(search.toLowerCase()),
  )
  const atLimit = data !== null && data.total >= data.quota
  const addMonitor = () => {
    setEditing(undefined)
    setDialog('add')
  }
  const initial = user.email[0].toUpperCase()
  const title = {
    overview: 'Overview',
    websites: 'Websites',
    global: 'Global monitor',
    analytics: 'Analytics',
  }[page]
  const healthy = monitors.filter((item) => item.status === 'UP').length
  function updateMeasurement(item: Monitor) {
    setData(
      (previous) =>
        previous && {
          ...previous,
          items: previous.items.map((m) => (m.id === item.id ? item : m)),
        },
    )
  }

  return (
    <div className="app-shell">
      <a
        className="skip-link"
        href="#main-content"
        inert={mobileOpen}
        onClick={(event) => {
          event.preventDefault()
          document.getElementById('main-content')?.focus()
          document.getElementById('main-content')?.scrollIntoView({ block: 'start' })
        }}
      >
        Skip to content
      </a>
      {mobileOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <aside className={`sidebar ${mobileOpen ? 'is-open' : ''}`}>
        <div className="sidebar-logo">
          <Brand />
          <span className="version-badge">BETA</span>
          <button
            id="close-navigation"
            className="icon-button mobile-close"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>
        <div className="workspace-switch">
          <span className="workspace-icon">{initial}</span>
          <span>
            <strong>My workspace</strong>
            <small>Personal · Free plan</small>
          </span>
        </div>
        <div className="nav-section-label">WORKSPACE</div>
        <nav aria-label="Main navigation" className="main-nav">
          <a
            href="#overview"
            className={page === 'overview' ? 'active' : ''}
            aria-current={page === 'overview' ? 'page' : undefined}
          >
            <LayoutDashboard size={18} />
            Overview
            <span className="nav-active-dot" />
          </a>
          <a
            href="#websites"
            className={page === 'websites' ? 'active' : ''}
            aria-current={page === 'websites' ? 'page' : undefined}
          >
            <Globe2 size={18} />
            Websites<span className="nav-count">{data?.total ?? '—'}</span>
          </a>
          <a
            href="#global"
            className={page === 'global' ? 'active' : ''}
            aria-current={page === 'global' ? 'page' : undefined}
          >
            <Radar size={18} />
            Global monitor
          </a>
          <button disabled title="Incident detection follows the real check engine">
            <TriangleAlert size={18} />
            Incidents<span className="soon-label">SOON</span>
          </button>
          <a
            href="#analytics"
            className={page === 'analytics' ? 'active' : ''}
            aria-current={page === 'analytics' ? 'page' : undefined}
          >
            <Activity size={18} />
            Analytics
          </a>
        </nav>
        <div className="nav-section-label learn-label">LEARN & EXPERIMENT</div>
        <nav className="main-nav learning-nav" aria-label="Learning tools">
          <button disabled title="Deterministic simulations arrive in Phase 4">
            <FlaskConical size={18} />
            Playground<span className="soon-label">SOON</span>
          </button>
          <button
            disabled
            title="Privileged lab experiments are disabled until safety controls ship"
          >
            <ShieldCheck size={18} />
            Recovery lab
            <span className="lock-symbol">
              <LockIcon />
            </span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <span className="note-icon">
              <Sparkles size={17} />
            </span>
            <strong>Small steps. Strong foundations.</strong>
            <p>Your reliability journey starts with a single website.</p>
            <button onClick={() => setDialog('guide')}>
              Explore the quick guide <ArrowUpRight size={14} />
            </button>
          </div>
          <button className="settings-link" onClick={() => setDialog('settings')}>
            <Settings2 size={17} />
            Workspace settings
          </button>
          <div className="sidebar-user">
            <span className="avatar">{initial}</span>
            <span>
              <strong>Personal account</strong>
              <small title={user.email}>{user.email}</small>
            </span>
            <button
              className="icon-button"
              aria-label="Sign out"
              title="Sign out"
              onClick={logout}
              disabled={loggingOut}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell" inert={mobileOpen}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>{title}</strong>
          </div>
          <div className="topbar-right">
            <span className={`connection-indicator ${apiConnected ? 'connected' : ''}`}>
              <span className="status-dot" />
              {apiConnected === null
                ? 'Connecting'
                : apiConnected
                  ? 'API connected'
                  : 'API unavailable'}
            </span>
            <span className="topbar-divider" />
            <button className="text-button" onClick={() => setDialog('guide')}>
              <BookOpen size={15} />
              <span>Quick guide</span>
            </button>
            <button
              className="avatar avatar-button"
              aria-label="Account settings"
              onClick={() => setDialog('settings')}
            >
              {initial}
            </button>
          </div>
        </header>
        <main className="content" id="main-content" tabIndex={-1}>
          <section className="page-heading">
            <div>
              <div className="eyebrow page-eyebrow">YOUR RELIABILITY WORKSPACE</div>
              <h1>
                {title}
                <span className="real-badge">
                  <span /> REAL
                </span>
              </h1>
              <p>
                {page === 'overview'
                  ? 'A little clarity for everything you keep online.'
                  : 'One place for your public websites and endpoints.'}
              </p>
            </div>
            <div className="heading-actions">
              <button
                className="button button-secondary refresh-button"
                onClick={refresh}
                disabled={loading}
              >
                <RefreshCw size={15} className={loading ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
              <button
                className="button button-primary"
                onClick={addMonitor}
                disabled={atLimit || !data}
                title={atLimit ? 'Your 10-monitor limit has been reached' : undefined}
              >
                <Plus size={17} />
                Add website
              </button>
            </div>
          </section>
          <div className="release-notice">
            <Info size={15} />
            <p>
              <strong>Real monitoring. Evidence first.</strong> Checks and charts appear only after
              workers report. Missing or stale observations stay UNKNOWN. Incidents and alerts are
              not active yet.
            </p>
            <button onClick={() => setDialog('guide')}>
              What’s included <ArrowUpRight size={13} />
            </button>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <TriangleAlert size={18} />
              <span>{error}</span>
              <button onClick={refresh} className="text-button">
                Try again
              </button>
            </div>
          )}
          {page === 'overview' && (
            <>
              <section className="welcome-card">
                <div className="welcome-copy">
                  <span className="welcome-kicker">
                    <span className="mini-spark">✦</span> A CLEARER PICTURE STARTS HERE
                  </span>
                  <h2>
                    {monitors.length
                      ? 'Your workspace is taking shape.'
                      : 'Your next chapter: fewer blind spots.'}
                  </h2>
                  <p>
                    {monitors.length
                      ? 'Your websites are saved. View measured checks, timing breakdowns and regional coverage—never assumed uptime.'
                      : 'Bring your websites together. Build a clearer picture of their health, one honest signal at a time.'}
                  </p>
                  <button onClick={() => setDialog('guide')} className="welcome-link">
                    Meet your workspace <ArrowRight size={15} />
                  </button>
                </div>
                <div className="welcome-art" aria-hidden="true">
                  <div className="art-grid" />
                  <div className="art-ring ring-outer" />
                  <div className="art-ring ring-inner" />
                  <div className="art-core">
                    <Activity size={36} strokeWidth={1.8} />
                  </div>
                  <span className="art-node node-a">
                    <Globe2 size={18} />
                  </span>
                  <span className="art-node node-b">
                    <Server size={17} />
                  </span>
                  <span className="art-dot dot-a" />
                  <span className="art-dot dot-b" />
                  <span className="art-caption">CLARITY, BY DESIGN</span>
                </div>
              </section>
              <section className="stats-grid" aria-label="Workspace summary">
                <Stat
                  label="Total websites"
                  value={data ? String(data.total).padStart(2, '0') : '—'}
                  icon={<Globe2 size={17} />}
                  hint={
                    data
                      ? `${data.quota - data.total} of ${data.quota} slots available`
                      : 'Loading your workspace'
                  }
                />
                <Stat
                  label="Awaiting first check"
                  value={data ? String(awaiting).padStart(2, '0') : '—'}
                  icon={<Clock3 size={17} />}
                  hint="No observations yet"
                  tone="amber"
                />
                <Stat
                  label="Paused monitors"
                  value={data ? String(paused).padStart(2, '0') : '—'}
                  icon={<Pause size={17} />}
                  hint="Intentionally on standby"
                  tone="slate"
                />
                <Stat
                  label="Healthy websites"
                  value={data ? String(healthy).padStart(2, '0') : '—'}
                  icon={<SlidersHorizontal size={17} />}
                  hint="All configured regions have fresh evidence"
                  tone="violet"
                />
              </section>
            </>
          )}
          {(page === 'overview' || page === 'websites') && (
            <div className={`dashboard-grid ${page === 'websites' ? 'websites-layout' : ''}`}>
              <section className="panel monitor-panel" aria-labelledby="websites-title">
                <div className="panel-heading">
                  <div>
                    <h2 id="websites-title">
                      Your websites <span className="count-badge">{data?.total ?? '—'}</span>
                    </h2>
                    <p>Real endpoints. No assumptions.</p>
                  </div>
                  <span className="panel-meta">
                    <span className="status-dot" /> OBSERVATIONS
                  </span>
                </div>
                <div className="table-toolbar">
                  <div className="filter-tabs" role="group" aria-label="Filter monitors">
                    {(['all', 'awaiting', 'paused'] as Filter[]).map((item) => (
                      <button
                        key={item}
                        className={filter === item ? 'selected' : ''}
                        aria-pressed={filter === item}
                        onClick={() => setFilter(item)}
                      >
                        {item === 'all'
                          ? 'All websites'
                          : item === 'awaiting'
                            ? 'Awaiting'
                            : 'Paused'}
                        <span>
                          {data
                            ? item === 'all'
                              ? data.total
                              : item === 'awaiting'
                                ? awaiting
                                : paused
                            : '—'}
                        </span>
                      </button>
                    ))}
                  </div>
                  <div className="search-field">
                    <Search size={15} />
                    <input
                      aria-label="Search websites"
                      placeholder="Search websites…"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                    />
                  </div>
                </div>
                {loading && !data ? (
                  <div className="panel-loading" role="status">
                    <RefreshCw size={22} className="spin" />
                    <p>Loading your workspace…</p>
                  </div>
                ) : !data ? (
                  <div className="empty-state">
                    <TriangleAlert size={30} />
                    <h3>We couldn’t load your websites.</h3>
                    <p>Your saved configuration hasn’t changed.</p>
                    <button className="button button-secondary" onClick={refresh}>
                      Try again
                    </button>
                  </div>
                ) : monitors.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-art" aria-hidden="true">
                      <span className="empty-orbit" />
                      <span className="empty-globe">
                        <Globe2 size={29} strokeWidth={1.4} />
                      </span>
                      <span className="empty-plus">
                        <Plus size={13} />
                      </span>
                      <span className="empty-particle one" />
                      <span className="empty-particle two" />
                    </div>
                    <h3>A home for your first website.</h3>
                    <p>
                      Add a public endpoint to get your workspace ready.
                      <br />
                      We’ll keep the configuration. You keep the peace of mind.
                    </p>
                    <button className="button button-primary" onClick={addMonitor}>
                      <Plus size={16} />
                      Add your first website
                    </button>
                    <small>
                      <ShieldCheck size={12} /> Public HTTP(S) only <span>·</span> Bounded requests
                      · authorized endpoints only
                    </small>
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="empty-state compact-empty">
                    <Search size={28} />
                    <h3>No websites match.</h3>
                    <p>Try a different search or filter.</p>
                    <button
                      className="button button-secondary"
                      onClick={() => {
                        setSearch('')
                        setFilter('all')
                      }}
                    >
                      Clear filters
                    </button>
                  </div>
                ) : (
                  <div
                    className="table-scroll"
                    tabIndex={0}
                    role="region"
                    aria-label="Website monitors"
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>
                            WEBSITE <ArrowDown size={10} />
                          </th>
                          <th>STATUS</th>
                          <th>UPTIME</th>
                          <th>RESPONSE</th>
                          <th>
                            <span className="sr-only">Actions</span>
                            <MoreHorizontal size={16} />
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((monitor) => (
                          <tr key={monitor.id}>
                            <td>
                              <div className="website-cell">
                                <span
                                  className={`website-avatar ${monitor.status === 'PAUSED' ? 'muted-avatar' : ''}`}
                                >
                                  {monitor.name[0].toUpperCase()}
                                </span>
                                <div>
                                  <button
                                    className="measurement-link"
                                    aria-label={`View measurements for ${monitor.name}`}
                                    onClick={() => setMeasuring(monitor)}
                                  >
                                    {monitor.name}
                                  </button>
                                  <a
                                    href={monitor.target_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {displayUrl(monitor.target_url)}
                                    <ArrowUpRight size={11} />
                                  </a>
                                </div>
                              </div>
                            </td>
                            <td>
                              <span className={`monitor-status ${monitor.status.toLowerCase()}`}>
                                <span className="status-dot" />
                                {monitor.status}
                              </span>
                              <small className="cell-subtext">
                                {monitor.status === 'PAUSED'
                                  ? 'On standby'
                                  : monitor.last_checked_at
                                    ? timestamp(monitor.last_checked_at)
                                    : 'Awaiting data'}
                              </small>
                            </td>
                            <td>
                              <span className="no-measurement">
                                {percent(monitor.availability_percent)}
                              </span>
                              <small className="cell-subtext">
                                {monitor.eligible_checks
                                  ? `${monitor.eligible_checks} samples · 24h`
                                  : 'No check data'}
                              </small>
                            </td>
                            <td>
                              <span className="no-measurement">{ms(monitor.response_time_ms)}</span>
                              <small className="cell-subtext">
                                {monitor.response_time_ms === null
                                  ? 'Not measured'
                                  : 'Latest observed response'}
                              </small>
                            </td>
                            <td>
                              <div className="row-actions">
                                <button
                                  className="icon-button"
                                  aria-label={`Edit ${monitor.name}`}
                                  title="Edit monitor"
                                  disabled={busyId !== null}
                                  onClick={() => {
                                    setEditing(monitor)
                                    setDialog('add')
                                  }}
                                >
                                  <Pencil size={14} />
                                </button>
                                <button
                                  className="icon-button"
                                  aria-label={`${monitor.status === 'PAUSED' ? 'Resume' : 'Pause'} ${monitor.name}`}
                                  title={monitor.status === 'PAUSED' ? 'Resume' : 'Pause'}
                                  disabled={busyId !== null}
                                  onClick={() => togglePause(monitor)}
                                >
                                  {monitor.status === 'PAUSED' ? (
                                    <Play size={14} />
                                  ) : (
                                    <Pause size={14} />
                                  )}
                                </button>
                                <button
                                  className="icon-button danger-hover"
                                  aria-label={`Delete ${monitor.name}`}
                                  title="Delete monitor"
                                  disabled={busyId !== null}
                                  onClick={() => {
                                    setDeleting(monitor)
                                    setActionError('')
                                  }}
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="table-footer">
                  <span>
                    <LockIcon /> Only visible to you
                  </span>
                  <span>
                    {data ? `${data.total} / ${data.quota}` : '—'} monitors{' '}
                    <span className="footer-dot">·</span> Free workspace
                  </span>
                </div>
              </section>
              <aside className="right-column">
                <section className="panel setup-panel">
                  <div className="setup-heading">
                    <span className="setup-icon">
                      <CheckCheck size={18} />
                    </span>
                    <span>{monitors.length ? '2' : '1'} OF 3 STEPS</span>
                  </div>
                  <h2>Make yourself at home.</h2>
                  <p>
                    A solid setup is the first step
                    <br />
                    toward a more reliable website.
                  </p>
                  <div
                    className="setup-progress"
                    aria-label={`${monitors.length ? 2 : 1} of 3 setup steps complete`}
                  >
                    <span />
                    <span className={monitors.length ? 'filled' : ''} />
                    <span />
                  </div>
                  <div className="setup-step complete">
                    <span className="step-marker">
                      <Check size={12} />
                    </span>
                    <div>
                      <strong>Create a workspace</strong>
                      <small>Your own corner of UptimeX.</small>
                    </div>
                  </div>
                  <button
                    className={`setup-step ${monitors.length ? 'complete' : 'current'}`}
                    onClick={addMonitor}
                    disabled={atLimit || !data}
                  >
                    <span className="step-marker">
                      {monitors.length ? <Check size={12} /> : '2'}
                    </span>
                    <div>
                      <strong>Add your first website</strong>
                      <small>
                        {monitors.length
                          ? 'Configuration safely saved.'
                          : 'Start with a public endpoint.'}
                      </small>
                    </div>
                    {!monitors.length && <ArrowUpRight size={15} />}
                  </button>
                  <div className="setup-step pending">
                    <span className="step-marker">3</span>
                    <div>
                      <strong>Collect your first signal</strong>
                      <small>
                        {monitors.some((m) => m.last_checked_at)
                          ? 'Real observation received.'
                          : 'Waiting for a worker observation.'}
                      </small>
                    </div>
                    <LockIcon />
                  </div>
                </section>
                <section className="honest-card">
                  <span className="honest-icon">
                    <ShieldCheck size={18} />
                  </span>
                  <h3>Unknown ≠ unhealthy.</h3>
                  <p>
                    No check data? We say so. A monitor only becomes UP after a real, trustworthy
                    observation.
                  </p>
                  <button onClick={() => setDialog('guide')}>
                    Our approach to monitoring <ArrowUpRight size={13} />
                  </button>
                </section>
              </aside>
            </div>
          )}
          {(page === 'global' || page === 'analytics') && (
            <FleetHealth
              monitors={monitors}
              onSelect={setMeasuring}
              analytics={page === 'analytics'}
            />
          )}
          {page === 'overview' && (
            <section className="journey-strip" aria-label="Product roadmap">
              <div className="journey-intro">
                <span className="eyebrow">THE BIGGER PICTURE</span>
                <strong>Observe. Understand. Recover.</strong>
              </div>
              <div className="journey-step current">
                <span>
                  <Globe2 size={17} />
                </span>
                <div>
                  <strong>Observe</strong>
                  <small>Your starting point</small>
                </div>
                <span className="journey-label">IN PROGRESS</span>
              </div>
              <ChevronRight className="journey-chevron" size={15} />
              <div className="journey-step">
                <span>
                  <Search size={17} />
                </span>
                <div>
                  <strong>Understand</strong>
                  <small>Evidence-led incidents</small>
                </div>
              </div>
              <ChevronRight className="journey-chevron" size={15} />
              <div className="journey-step future">
                <span>
                  <FlaskConical size={17} />
                </span>
                <div>
                  <strong>Recover</strong>
                  <small>Learn safely in simulation</small>
                </div>
              </div>
            </section>
          )}
          <footer className="content-footer">
            <span>
              <span className="footer-logo">
                <Activity size={13} /> UptimeX
              </span>
              <span className="footer-divider">/</span> Built for signal. Not noise.
            </span>
            <span>
              Observatory v0.2 <span className="footer-dot">·</span> All timestamps in UTC
            </span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <span>
            <Check size={15} />
          </span>
          {toast}
          <button
            className="icon-button"
            aria-label="Dismiss notification"
            onClick={() => setToast('')}
          >
            <X size={14} />
          </button>
        </div>
      )}
      {measuring && (
        <MonitorDetails
          monitor={measuring}
          onClose={() => setMeasuring(null)}
          onUpdated={updateMeasurement}
        />
      )}
      {dialog === 'add' && (
        <MonitorDialog
          monitor={editing}
          onClose={() => {
            setDialog(null)
            setEditing(undefined)
          }}
          onSaved={save}
        />
      )}
      {dialog === 'guide' && (
        <Modal
          title="A little clarity, before you start."
          onClose={() => setDialog(null)}
          className="guide-modal"
        >
          <div className="guide-body">
            <span className="guide-eyebrow">
              <span className="status-dot amber" /> OBSERVATORY · REAL MEASUREMENTS
            </span>
            <h3>
              Real configuration.
              <br />
              <span>No pretend observations.</span>
            </h3>
            <p>
              This release measures authorized public endpoints. Here’s exactly what’s ready—and
              what isn’t.
            </p>
            <div className="guide-list">
              <div>
                <Check size={17} />
                <span>
                  <strong>Available today</strong>Private accounts, saved website monitors, URL
                  safety checks, real bounded HTTP checks, timing history, regional evidence and
                  measured charts.
                </span>
              </div>
              <div>
                <Clock3 size={17} />
                <span>
                  <strong>Coming in the next slices</strong>Incident detection, notifications,
                  public status pages and production hardening. AWS regional deployment still
                  requires its live verification gate.
                </span>
              </div>
              <div>
                <FlaskConical size={17} />
                <span>
                  <strong>Later, in separate domains</strong>SIMULATED Playground events and
                  privileged LAB telemetry will never mix with REAL monitoring.
                </span>
              </div>
            </div>
            <div className="info-box">
              <Info size={17} />
              <p>
                Workers revalidate DNS on each hop, pin actual public destinations, verify TLS and
                cap time, redirects and response bytes. No response bodies are stored. Uptime is
                successful eligible checks divided by eligible checks; coverage is separate.
              </p>
            </div>
            <a className="api-reference" href="/api/docs" target="_blank" rel="noreferrer">
              Explore the API reference <ArrowUpRight size={14} />
            </a>
          </div>
          <div className="guide-footer">
            <button className="button button-primary" onClick={() => setDialog(null)}>
              Got it <Check size={15} />
            </button>
          </div>
        </Modal>
      )}
      {dialog === 'settings' && (
        <Modal title="Workspace settings" onClose={() => setDialog(null)}>
          <div className="settings-body">
            <div className="settings-account">
              <span className="avatar">{initial}</span>
              <div>
                <h3>Personal workspace</h3>
                <p>{user.email}</p>
              </div>
            </div>
            <dl className="settings-list">
              <div>
                <dt>Plan</dt>
                <dd>Free · {data?.quota ?? 10} monitors</dd>
              </div>
              <div>
                <dt>Data storage</dt>
                <dd>Server-side database</dd>
              </div>
              <div>
                <dt>Session</dt>
                <dd>Revocable server-side session</dd>
              </div>
              <div>
                <dt>Background checks</dt>
                <dd className="amber-text">
                  {data?.checks_enabled
                    ? 'Enabled · see Global monitor for heartbeat'
                    : 'Disabled by operator'}
                </dd>
              </div>
              <div>
                <dt>Release</dt>
                <dd>Observatory v0.2.0</dd>
              </div>
            </dl>
            <p className="settings-note">
              <Info size={15} /> Account recovery, email verification and team settings are not
              available in this slice.
            </p>
            <button className="button button-secondary" onClick={logout} disabled={loggingOut}>
              <LogOut size={15} />
              {loggingOut ? 'Signing out…' : 'Sign out of workspace'}
            </button>
          </div>
        </Modal>
      )}
      {deleting && (
        <Modal
          title="Delete this monitor?"
          onClose={() => setDeleting(null)}
          busy={busyId !== null}
        >
          <div className="delete-body">
            <span className="delete-icon">
              <Trash2 size={25} />
            </span>
            <p>
              <strong>{deleting.name}</strong> will be permanently removed from your workspace. This
              cannot be undone.
            </p>
            <small>
              All associated check history and queued jobs are permanently removed. Pause instead to
              retain history.
            </small>
            {actionError && (
              <div className="form-error" role="alert">
                {actionError}
              </div>
            )}
          </div>
          <div className="delete-footer">
            <button
              className="button button-secondary"
              onClick={() => setDeleting(null)}
              disabled={busyId !== null}
            >
              Keep monitor
            </button>
            <button
              className="button button-danger"
              onClick={removeMonitor}
              disabled={busyId !== null}
            >
              {busyId ? 'Deleting…' : 'Delete monitor'}
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function LockIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M5.5 7V4.5a2.5 2.5 0 0 1 5 0V7" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 9.5v1.5" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  )
}

function Stat({
  label,
  value,
  unit,
  icon,
  hint,
  tone = 'teal',
}: {
  label: string
  value: string
  unit?: string
  icon: ReactNode
  hint: string
  tone?: string
}) {
  return (
    <article className={`stat-card stat-${tone}`}>
      <div className="stat-label">
        {label}
        <span>{icon}</span>
      </div>
      <div className="stat-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      <div className="stat-hint">
        <span className="status-dot" />
        {hint}
      </div>
    </article>
  )
}
