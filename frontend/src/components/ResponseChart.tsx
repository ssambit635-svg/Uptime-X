import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Analytics, AnalyticsWindow } from '../lib/api'
import { timestamp } from '../lib/format'

export default function ResponseChart({
  data,
  window,
}: {
  data: Analytics['trend']
  window: AnalyticsWindow
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart
        data={data.map((point) => ({
          ...point,
          time: Date.parse(point.start),
        }))}
        margin={{ top: 14, right: 24, bottom: 4, left: 2 }}
      >
        <CartesianGrid stroke="#243044" strokeDasharray="3 4" />
        <XAxis
          dataKey="time"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(value: number) =>
            new Date(value)
              .toISOString()
              .slice(window === '24h' ? 11 : 5, window === '24h' ? 16 : 10)
          }
          stroke="#8795ac"
          minTickGap={36}
        />
        <YAxis stroke="#8795ac" width={48} />
        <Tooltip
          contentStyle={{ background: '#142034', border: '1px solid #304057' }}
          labelFormatter={(value) => timestamp(new Date(Number(value)).toISOString())}
        />
        <Line
          dataKey="average_ms"
          name="Average (ms)"
          stroke="#46dbc5"
          dot={{ r: 2 }}
          connectNulls={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="p95_ms"
          name="p95 (ms)"
          stroke="#aa9af4"
          dot={false}
          connectNulls={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
