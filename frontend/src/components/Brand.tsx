import { Activity } from 'lucide-react'

export function Brand({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand ${small ? 'brand-small' : ''}`}>
      <span className="brand-mark">
        <Activity size={21} strokeWidth={2.6} aria-hidden="true" />
      </span>
      <span>
        Uptime<span className="brand-x">X</span>
      </span>
    </span>
  )
}
