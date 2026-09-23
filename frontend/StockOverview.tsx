import { ArrowUpRight } from 'lucide-react';
import type { Run } from './types';

export function StockOverview({ run, onOpen }: { run: Run; onOpen: () => void }) {
  const groups = [
    { label: 'Риск дефицита', count: run.summary.critical, color: '#8065ff' },
    {
      label: 'К пополнению',
      count: run.rows.filter((row) => row.urgency === 'plan').length,
      color: '#3899fa',
    },
    { label: 'В норме', count: run.rows.filter((row) => row.urgency === 'healthy').length, color: '#dfe3ec' },
  ];
  const total = run.rows.length;
  const point = (fraction: number) => {
    const angle = Math.PI * (1 - fraction);
    return `${160 + 126 * Math.cos(angle)},${166 - 126 * Math.sin(angle)}`;
  };
  return (
    <section className="panel stock-overview">
      <div className="panel-heading">
        <h2>Состояние запасов</h2>
        <button className="icon-button" onClick={onOpen} aria-label="Открыть рекомендации по запасам">
          <ArrowUpRight size={18} />
        </button>
      </div>
      <div className="stock-summary">
        <strong>
          {run.summary.to_order} <span>к пополнению</span>
        </strong>
        <p>По текущему прогнозу спроса</p>
      </div>
      <svg
        className="stock-gauge"
        viewBox="0 0 320 195"
        role="img"
        aria-label={groups.map((group) => `${group.label}: ${group.count}`).join(', ')}
      >
        {Array.from({ length: 60 }, (_, index) => {
          const position = ((index + 0.5) / 60) * total;
          const color =
            total === 0
              ? '#e9ebf0'
              : position < groups[0].count
                ? groups[0].color
                : position < groups[0].count + groups[1].count
                  ? groups[1].color
                  : groups[2].color;
          return (
            <path
              key={index}
              d={`M ${point((index + 0.08) / 60)} A 126 126 0 0 1 ${point((index + 0.92) / 60)}`}
              fill="none"
              stroke={color}
              strokeWidth="25"
            />
          );
        })}
        <text x="160" y="139" textAnchor="middle" className="gauge-total">
          {total}
        </text>
        <text x="160" y="161" textAnchor="middle" className="gauge-caption">
          позиций в расчёте
        </text>
      </svg>
      <div className="stock-legend">
        {groups.map((group) => (
          <div key={group.label}>
            <span>
              <i style={{ background: group.color }} />
              {group.label}
            </span>
            <strong>{group.count}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}
