import { useEffect, useState } from 'react'
import { RefreshCw, TriangleAlert } from 'lucide-react'
import { api, ApiError, errorMessage } from './lib/api'
import type { User } from './lib/api'
import { AuthScreen } from './components/AuthScreen'
import { Brand } from './components/Brand'
import { Dashboard } from './components/Dashboard'

export function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api
      .me()
      .then((result) => {
        if (alive) setUser(result)
      })
      .catch((err: unknown) => {
        if (alive && !(err instanceof ApiError && err.status === 401)) setError(errorMessage(err))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    const expired = () => setUser(null)
    window.addEventListener('uptimex:session-expired', expired)
    return () => {
      alive = false
      window.removeEventListener('uptimex:session-expired', expired)
    }
  }, [])

  if (loading)
    return (
      <div className="app-loading">
        <Brand />
        <RefreshCw className="spin" size={22} />
        <p>Opening your workspace…</p>
      </div>
    )
  if (error)
    return (
      <div className="app-loading">
        <Brand />
        <TriangleAlert size={28} />
        <h1>Let’s reconnect.</h1>
        <p role="alert">{error}</p>
        <button className="button button-primary" onClick={() => window.location.reload()}>
          Try again
        </button>
      </div>
    )
  if (!user) return <AuthScreen onAuthenticated={setUser} />
  return <Dashboard user={user} onLogout={() => setUser(null)} />
}
