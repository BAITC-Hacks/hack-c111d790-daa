import { useId, useState } from 'react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Row } from './types';

export function DemandChart({ row, expanded = false }: { row: Row; expanded?: boolean }) {
  const [period, setPeriod] = useState(90);
  const bandId = useId().replace(/:/g, '');
  // Weekly means keep long histories readable and retain per-day units.
  const buckets = new Map<
    string,
    {
      date: string;
      actual?: number[];
      restored?: number[];
      forecast?: number[];
      lower?: number[];
      upper?: number[];
    }
  >();
  const add = (date: string, values: Record<string, number>) => {
    const d = new Date(`${date}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    const key = d.toISOString().slice(0, 10);
    const bucket = buckets.get(key) || { date: key };
    for (const [k, v] of Object.entries(values)) {
      const field = k as 'actual' | 'restored' | 'forecast' | 'lower' | 'upper';
      (bucket[field] ||= []).push(v);
    }
    buckets.set(key, bucket);
  };
  row.history.slice(-period).forEach((p) => add(p.date, { actual: p.actual, restored: p.restored }));
  row.forecast.forEach((p) => add(p.date, { forecast: p.forecast, lower: p.lower, upper: p.upper }));
  const mean = (v?: number[]) =>
    v ? Math.round((v.reduce((a, b) => a + b, 0) / v.length) * 10) / 10 : undefined;
  const points = [...buckets.values()].map((b) => ({
    date: b.date,
    actual: mean(b.actual),
    restored: mean(b.restored),
    forecast: mean(b.forecast),
    band: b.lower ? [mean(b.lower), mean(b.upper)] : undefined,
  }));
  const boundary = points.find((p) => p.forecast !== undefined)?.date;
  return (
    <>
      {expanded && (
        <div className="period-switch" aria-label="Период графика">
          {[90, 365, 730].map((p) => (
            <button key={p} className={period === p ? 'active' : ''} onClick={() => setPeriod(p)}>
              {p === 730 ? '2 года' : `${p} дней`}
            </button>
          ))}
        </div>
      )}
      <div className="chart" role="img" aria-label={`История и прогноз спроса: ${row.name}`}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} margin={{ top: 10, right: 8, left: -24, bottom: 0 }}>
            <defs>
              <pattern
                id={bandId}
                width="7"
                height="7"
                patternUnits="userSpaceOnUse"
                patternTransform="rotate(35)"
              >
                <rect width="7" height="7" fill="#f5f9ff" />
                <line x1="0" y1="0" x2="0" y2="7" stroke="#bcdcff" strokeWidth="2" />
              </pattern>
            </defs>
            <CartesianGrid stroke="#edf0f4" strokeDasharray="3 4" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={(d) =>
                new Date(`${d}T12:00:00`).toLocaleDateString('ru', { day: 'numeric', month: 'short' })
              }
              tickLine={false}
              axisLine={false}
              minTickGap={35}
              tick={{ fontSize: 11, fill: '#8a8f9d' }}
            />
            <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#8a8f9d' }} />
            <Tooltip
              labelFormatter={(d) => `Неделя с ${new Date(`${d}T12:00:00`).toLocaleDateString('ru')}`}
              contentStyle={{
                borderRadius: 12,
                border: '1px solid #ececf2',
                fontSize: 12,
                boxShadow: '0 8px 28px #20203810',
              }}
            />
            <Area
              type="monotone"
              dataKey="band"
              name="Ориентир неопределённости"
              stroke="none"
              fill={`url(#${bandId})`}
              fillOpacity={0.8}
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="Фактические продажи"
              stroke="#c6cad4"
              strokeWidth={1.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="restored"
              name="Регулярный спрос"
              stroke="#8065ff"
              strokeWidth={2.5}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="forecast"
              name="Прогноз"
              stroke="#3899fa"
              strokeDasharray="5 4"
              strokeWidth={2.5}
              dot={false}
            />
            <ReferenceLine x={boundary} stroke="#d4d7e0" strokeDasharray="3 4" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="chart-legend">
        <span>
          <i className="legend-dot gray" />
          Продажи
        </span>
        <span>
          <i className="legend-dot purple" />
          Регулярный спрос
        </span>
        <span>
          <i className="legend-dot blue" />
          Прогноз
        </span>
        <small>Среднее за неделю, {row.unit}/день</small>
      </div>
    </>
  );
}
