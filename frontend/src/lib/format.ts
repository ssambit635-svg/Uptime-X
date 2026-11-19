export const timestamp = (value: string | null) =>
  value
    ? `${new Date(value).toLocaleString('en-GB', { timeZone: 'UTC', hour12: false })} UTC`
    : 'Not observed'
export const ms = (value: number | null) => (value === null ? '—' : `${value.toFixed(1)} ms`)
export const percent = (value: number | null) => (value === null ? '—' : `${value.toFixed(2)}%`)
