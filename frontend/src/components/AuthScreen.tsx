import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Eye,
  EyeOff,
  Globe2,
  LockKeyhole,
  ShieldCheck,
} from 'lucide-react'
import { api, ApiError, errorMessage } from '../lib/api'
import type { User } from '../lib/api'
import { Brand } from './Brand'

export function AuthScreen({ onAuthenticated }: { onAuthenticated: (user: User) => void }) {
  const [mode, setMode] = useState<'register' | 'login'>('register')
  const [visible, setVisible] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [sessionBlocked, setSessionBlocked] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setError('')
    setSessionBlocked(false)
    setPending(true)
    try {
      const user = await api.authenticate(
        mode,
        String(form.get('email')),
        String(form.get('password')),
      )
      onAuthenticated(user)
    } catch (err) {
      setError(errorMessage(err))
      setSessionBlocked(err instanceof ApiError && err.code === 'SESSION_NOT_ESTABLISHED')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="auth-page">
      <header className="auth-header">
        <Brand />
        <span className="release-tag">
          <span /> PHASE 01 <i>/</i> EARLY ACCESS
        </span>
      </header>
      <main className="auth-main">
        <section className="auth-story">
          <div className="eyebrow">
            <span className="tiny-line" /> THE INTERNET’S HEALTH, UNDER ONE ROOF.
          </div>
          <h1>
            Less uncertainty.
            <br />
            More <span>uptime.</span>
          </h1>
          <p className="auth-intro">
            A calmer place to understand your websites.
            <br className="desktop-break" /> Start with a workspace built around clarity.
          </p>
          <div className="signal-illustration" aria-hidden="true">
            <div className="signal-grid" />
            <div className="signal-orbit orbit-one" />
            <div className="signal-orbit orbit-two" />
            <div className="signal-node node-globe">
              <Globe2 size={29} />
            </div>
            <svg viewBox="0 0 480 140" className="signal-path">
              <path d="M54 75H165l18-30 24 60 20-42 16 12h183" />
            </svg>
            <div className="signal-node node-check">
              <ShieldCheck size={28} />
            </div>
            <div className="signal-label label-one">YOUR WEBSITES</div>
            <div className="signal-label label-two">A CLEARER PICTURE</div>
          </div>
          <div className="auth-features">
            <span>
              <Check size={15} /> A private workspace
            </span>
            <span>
              <Check size={15} /> Up to 10 monitors
            </span>
            <span>
              <Check size={15} /> No credit card
            </span>
          </div>
          <div className="honesty-note">
            <span className="status-dot amber" /> Foundation release. Real health checks are coming
            next.
          </div>
        </section>
        <section className="auth-card" aria-labelledby="auth-title">
          <span className="auth-icon">
            <LockKeyhole size={23} />
          </span>
          <h2 id="auth-title">{mode === 'register' ? 'Create your workspace' : 'Welcome back'}</h2>
          <p>
            {mode === 'register'
              ? 'Your next step toward a more reliable web.'
              : 'Let’s get you back to a clearer view.'}
          </p>
          <form onSubmit={submit} className="auth-form">
            <label htmlFor="email">Work email</label>
            <input
              id="email"
              name="email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              maxLength={320}
              required
              disabled={pending}
            />
            <label htmlFor="password">Password</label>
            <div className="password-field">
              <input
                id="password"
                name="password"
                type={visible ? 'text' : 'password'}
                placeholder={
                  mode === 'register' ? 'Create a strong password' : 'Enter your password'
                }
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                minLength={10}
                maxLength={128}
                required
                disabled={pending}
                aria-describedby="password-hint"
              />
              <button
                type="button"
                className="icon-button"
                aria-label={visible ? 'Hide password' : 'Show password'}
                onClick={() => setVisible(!visible)}
              >
                {visible ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </div>
            <small id="password-hint">At least 10 characters. Make it uniquely yours.</small>
            {error && (
              <div className="form-error" role="alert">
                {error}
              </div>
            )}
            {sessionBlocked && (
              <a
                className="button button-secondary session-help"
                href={window.location.href}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open preview in a new tab <ArrowUpRight size={14} />
              </a>
            )}
            <button className="button button-primary auth-submit" disabled={pending} type="submit">
              {pending ? 'One moment…' : mode === 'register' ? 'Create workspace' : 'Sign in'}
              <ArrowRight size={17} />
            </button>
          </form>
          <div className="auth-switch">
            {mode === 'register' ? 'Already have an account?' : 'New to UptimeX?'}{' '}
            <button
              disabled={pending}
              onClick={() => {
                setMode(mode === 'register' ? 'login' : 'register')
                setError('')
                setSessionBlocked(false)
              }}
            >
              {mode === 'register' ? 'Sign in' : 'Create a workspace'} <ArrowUpRight size={13} />
            </button>
          </div>
          <div className="auth-secure">
            <ShieldCheck size={14} /> Passwords are protected with Argon2id.
          </div>
        </section>
      </main>
      <footer className="auth-footer">
        <span>© {new Date().getUTCFullYear()} UptimeX</span>
        <span>Built for signal. Not noise.</span>
        <span className="mono">OBSERVE. UNDERSTAND. RECOVER.</span>
      </footer>
    </div>
  )
}
