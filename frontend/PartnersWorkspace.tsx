import { useEffect, useState } from 'react';
import {
  Database,
  Plus,
  Search,
  Sparkles,
  SlidersHorizontal,
  Download,
  FileSpreadsheet,
  ArrowRight,
} from 'lucide-react';
import {
  ResponsiveContainer,
  CartesianGrid,
  Line,
  ComposedChart,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from 'recharts';
import { api } from './api';
import { PartnerManual } from './PartnerManual';
import {
  type Company,
  type Product,
  type Forecast,
  type PartnerRun,
  formatNumber as fmt,
} from './partnerTypes';

export function PartnersWorkspace() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [company, setCompany] = useState('iek');
  const [catalog, setCatalog] = useState<{ total: number; items: Product[] }>({ total: 0, items: [] });
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [product, setProduct] = useState<Product | null>(null);
  const [run, setRun] = useState<PartnerRun | null>(null);
  const [runs, setRuns] = useState<PartnerRun[]>([]);
  const [manual, setManual] = useState<'edit' | 'new' | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [resultPage, setResultPage] = useState(0);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    api<Company[]>('/partners')
      .then(setCompanies)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    let active = true;
    setProduct(null);
    setRun(null);
    setRuns([]);
    setCatalog({ total: 0, items: [] });
    setSearch('');
    setOffset(0);
    setError('');
    api<PartnerRun[]>(`/partners/${company}/runs`)
      .then((r) => {
        if (active) {
          setRuns(r);
          if (r[0])
            api<PartnerRun>(`/partners/${company}/runs/${r[0].id}`)
              .then((v) => {
                if (active) setRun(v);
              })
              .catch((e) => {
                if (active) setError(e.message);
              });
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [company]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      api<{ total: number; items: Product[] }>(
        `/partners/${company}/products?limit=30&offset=${offset}&search=${encodeURIComponent(search)}`,
      )
        .then((v) => {
          if (active) setCatalog(v);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [company, search, offset, refresh]);
  const meta = companies.find((c) => c.id === company);
  const row = run?.rows.find((r) => r.sku === product?.sku);
  async function task(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка');
    } finally {
      setBusy('');
    }
  }
  async function select(sku: string) {
    await task('Открываем позицию…', async () =>
      setProduct(await api<Product>(`/partners/${company}/product?sku=${encodeURIComponent(sku)}`)),
    );
  }
  async function calculate(single = false) {
    await task('Рассчитываем и проверяем прогноз…', async () => {
      const r = await api<PartnerRun>(
        `/partners/${company}/calculate`,
        single && product ? { skus: [product.sku] } : { limit: 4000 },
      );
      setRun(r);
      setResultPage(0);
      setRuns(await api<PartnerRun[]>(`/partners/${company}/runs`));
    });
  }
  if (!meta)
    return (
      <section className="panel partner-card">
        <h1>Данные партнёров</h1>
        <p>{error || 'Архивы ещё не импортированы. Инструкция: README_PARTNER_DATA_IEK_SYSTEME_2026.md'}</p>
      </section>
    );
  return (
    <div className="partner-workspace">
      <div className="page-heading">
        <div>
          <span className="eyebrow">IEK · SYSTEME ELECTRIC</span>
          <h1>Данные партнёров</h1>
          <p>Исходные отчёты → проверяемый прогноз → обоснованный заказ.</p>
        </div>
        <button className="button secondary" disabled={!!busy} onClick={() => setManual('new')}>
          <Plus size={16} />
          Ручной ввод
        </button>
      </div>
      <div className="partner-toolbar">
        <div className="partner-switch" aria-label="Компания">
          {companies.map((c) => (
            <button
              disabled={!!busy}
              key={c.id}
              className={company === c.id ? 'selected' : ''}
              onClick={() => setCompany(c.id)}
            >
              {c.name}
            </button>
          ))}
        </div>
        <span className="muted">Срез {meta.snapshot_date} · оригинальные файлы</span>
        <button className="button primary" disabled={!!busy} onClick={() => void calculate()}>
          <Sparkles size={16} />
          Рассчитать компанию
        </button>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}
      {busy && (
        <div className="busy-banner" role="status">
          {busy}
        </div>
      )}
      <div className="partner-stats">
        {[
          ['Позиций в источниках', meta.products, 'По коду 1С, без дублирования'],
          ['С месячной историей', meta.monthly_sales_products, 'Полные месяцы до августа 2026'],
          ['Строк движения', meta.events.rows, `${fmt(meta.events.returns, 0)} возвратов / корректировок`],
          ['SKU с текущим остатком', meta.stock_snapshot_products, 'Область складов требует проверки'],
        ].map(([title, value, note]) => (
          <section className="panel partner-stat" key={title}>
            <Database size={18} />
            <span>{title}</span>
            <strong>{fmt(Number(value), 0)}</strong>
            <small>{note}</small>
          </section>
        ))}
      </div>
      <details className="panel partner-audit">
        <summary>
          <FileSpreadsheet size={17} />
          Что сохранено из файлов <span>{meta.sources.length} файлов</span>
        </summary>
        <div className="partner-audit-content">
          <p>
            Расхождения месячного отчёта с динамикой:{' '}
            <strong>
              {fmt(meta.reconciliation.mismatched, 0)} из {fmt(meta.reconciliation.compared, 0)} SKU-месяцев
            </strong>
            . Источники сохранены отдельно. Отрицательные движения — возвраты/корректировки, а не
            положительный спрос.
          </p>
          <ul>
            {meta.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          {meta.sources.map((s) => (
            <p key={s.file}>
              <strong>{s.file}</strong>
              <br />
              <small>{s.sheets.map((t) => `${t.name}: ${fmt(t.populated_rows, 0)} строк`).join(' · ')}</small>
            </p>
          ))}
        </div>
      </details>
      <div className="partner-grid">
        <section className="panel partner-catalog">
          <div className="panel-heading">
            <h2>Каталог</h2>
            <span className="muted">{fmt(catalog.total, 0)} SKU</span>
          </div>
          <div className="partner-search">
            <Search size={16} />
            <input
              aria-label="Поиск позиции партнёра"
              placeholder="Код, артикул или название"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setOffset(0);
              }}
            />
          </div>
          <div className="partner-product-list">
            {catalog.items.map((p) => (
              <button
                key={p.sku}
                disabled={!!busy}
                className={product?.sku === p.sku ? 'selected' : ''}
                onClick={() => void select(p.sku)}
              >
                <span>
                  <strong>{p.name}</strong>
                  <small>
                    {p.sku} · {p.supplier_sku || 'без артикула'}
                  </small>
                </span>
                <ArrowRight size={14} />
              </button>
            ))}
            {!catalog.items.length && <p className="muted">Позиции не найдены</p>}
          </div>
          <div className="partner-pagination">
            <button disabled={!offset} onClick={() => setOffset(offset - 30)}>
              Назад
            </button>
            <span>
              {offset + 1}–{Math.min(offset + 30, catalog.total)}
            </span>
            <button disabled={offset + 30 >= catalog.total} onClick={() => setOffset(offset + 30)}>
              Далее
            </button>
          </div>
        </section>
        <section className="panel partner-detail">
          {!product ? (
            <div className="empty">
              <Database size={30} />
              <h2>Выберите позицию</h2>
              <p>Проверьте исходные значения, дополните условия закупки и получите объяснение расчёта.</p>
            </div>
          ) : (
            <>
              <div className="panel-heading">
                <div>
                  <span className="eyebrow">
                    {product.sku} · {product.unit || 'единица не указана'}
                  </span>
                  <h2>{product.name}</h2>
                  <p>
                    {product.supplier_sku} · категория {product.category || 'не указана'}
                  </p>
                </div>
              </div>
              <div className="partner-toolbar">
                <button className="button secondary" disabled={!!busy} onClick={() => setManual('edit')}>
                  <SlidersHorizontal size={16} />
                  Уточнить данные
                </button>
                <button className="button primary" disabled={!!busy} onClick={() => void calculate(true)}>
                  <Sparkles size={16} />
                  Прогноз позиции
                </button>
              </div>
              <div className="partner-facts">
                {[
                  ['Свободный остаток', product.stock],
                  ['Минимальный заказ', product.moq],
                  ['Кратность', product.pack_size],
                  ['Закупочная цена, ₸', product.purchase_price],
                ].map(([label, v]) => (
                  <div key={label}>
                    <small>{label}</small>
                    <strong>{fmt(v as number | null)}</strong>
                  </div>
                ))}
              </div>
              {row ? (
                <ForecastDetail row={row} />
              ) : (
                <>
                  <p className="muted">
                    Месячные продажи из отчёта · {product.monthly_sales.length} наблюдений
                  </p>
                  <SalesChart
                    rows={product.monthly_sales.map((p) => ({ month: p.month, actual: p.quantity ?? 0 }))}
                  />
                  <p className="muted">
                    Запустите прогноз позиции для выбора модели и оценки на отложенных месяцах.
                  </p>
                </>
              )}
              <details className="partner-expand">
                <summary>Движения, возвраты и крупные документы</summary>
                <p>
                  Положительные движения: {fmt(product.event_summary?.gross)} {product.unit}.
                  Возвраты/корректировки: {fmt(product.event_summary?.returns)} {product.unit}. Документ не
                  является ID клиента; крупный объём требует проверки.
                </p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Дата</th>
                        <th>Документ</th>
                        <th>Количество</th>
                      </tr>
                    </thead>
                    <tbody>
                      {product.largest_documents?.map((d, i) => (
                        <tr key={i}>
                          <td>{d.date}</td>
                          <td>{d.document}</td>
                          <td>{fmt(d.quantity)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <details className="partner-expand">
                <summary>Поступления, исторические остатки и происхождение</summary>
                <p>
                  Поступлений: {product.inbound.length}. Исторические остатки не заменяют текущий доступный
                  запас. «СС реал»: {fmt(product.cost_of_sales)} — отдельно от закупочной цены.
                </p>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ожидаемая дата</th>
                        <th>Количество</th>
                        <th>Документ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {product.inbound.map((i, n) => (
                        <tr key={n}>
                          <td>{i.eta || 'Неизвестна'}</td>
                          <td>{fmt(i.quantity)}</td>
                          <td>{i.reference}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p>{product.monthly_stock.map((s) => `${s.month}: ${fmt(s.quantity)}`).join(' · ')}</p>
                {Object.entries(product.provenance).map(([k, v]) => (
                  <p key={k}>
                    <strong>{k}</strong>: {v}
                  </p>
                ))}
              </details>
              <details className="partner-expand">
                <summary>История ручных изменений · {product.revisions?.length || 0}</summary>
                {product.revisions?.map((r) => (
                  <p key={r.id}>
                    {r.created_at} — {r.note}
                  </p>
                ))}
              </details>
            </>
          )}
        </section>
      </div>
      <section className="panel partner-results">
        <div className="panel-heading">
          <div>
            <h2>Сохранённые рекомендации · {meta.name}</h2>
            <p>Черновик для проверки менеджером. Поставщику не отправляется.</p>
          </div>
          <div className="partner-toolbar">
            <select
              aria-label="Сохранённый расчёт"
              value={run?.id || ''}
              disabled={!!busy}
              onChange={(e) =>
                void task('Открываем расчёт…', async () => {
                  setRun(await api<PartnerRun>(`/partners/${company}/runs/${e.target.value}`));
                  setResultPage(0);
                })
              }
            >
              <option value="" disabled>
                Выберите расчёт
              </option>
              {runs.map((r) => (
                <option value={r.id} key={r.id}>
                  {new Date(r.created_at).toLocaleString('ru-RU')} · {r.summary.positions} SKU
                </option>
              ))}
            </select>
            {run && (
              <a className="button secondary" href={`/api/partners/${company}/runs/${run.id}/export`}>
                <Download size={16} />
                CSV
              </a>
            )}
          </div>
        </div>
        {run ? (
          <>
            <div className="partner-result-summary">
              <strong>{fmt(run.summary.positions, 0)} позиций</strong>
              <span>Заказ рассчитан: {fmt(run.summary.orders_ready, 0)}</span>
              <span>Нужны уточнения: {fmt(run.summary.needs_inputs, 0)}</span>
            </div>
            <div className="partner-quality">
              {Object.entries(run.summary.by_unit).map(([unit, m]) => (
                <div key={unit}>
                  <span>
                    WAPE · {unit} · {m.positions} SKU
                  </span>
                  <strong>{fmt(m.wape)}%</strong>
                  <small>Базовая модель: {fmt(m.baseline_wape)}% · меньше лучше</small>
                </div>
              ))}
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Позиция</th>
                    <th>Модель</th>
                    <th>Прогноз / первый месяц</th>
                    <th>К заказу</th>
                    <th>Что уточнить</th>
                  </tr>
                </thead>
                <tbody>
                  {run.rows.slice(resultPage * 30, (resultPage + 1) * 30).map((r) => (
                    <tr key={r.sku}>
                      <td>
                        <button className="partner-link" disabled={!!busy} onClick={() => void select(r.sku)}>
                          {r.name}
                        </button>
                        <small>{r.sku}</small>
                      </td>
                      <td>{r.model || 'Недостаточно истории'}</td>
                      <td>
                        {fmt(r.forecast[0]?.quantity)} {r.unit}
                      </td>
                      <td>
                        {fmt(r.quantity)} {r.quantity == null ? '' : r.unit}
                      </td>
                      <td>
                        {r.blocked.length
                          ? `${r.blocked.length} уточнений: ${r.blocked.slice(0, 2).join(', ')}`
                          : r.explanation}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="partner-pagination">
              <button disabled={!resultPage} onClick={() => setResultPage(resultPage - 1)}>
                Назад
              </button>
              <span>
                {resultPage + 1} / {Math.max(1, Math.ceil(run.rows.length / 30))}
              </span>
              <button
                disabled={(resultPage + 1) * 30 >= run.rows.length}
                onClick={() => setResultPage(resultPage + 1)}
              >
                Далее
              </button>
            </div>
          </>
        ) : (
          <div className="empty">
            <p>Рассчитайте компанию или отдельную позицию.</p>
          </div>
        )}
      </section>
      {manual && (
        <PartnerManual
          company={company}
          product={manual === 'edit' ? product : null}
          snapshot={meta.snapshot_date}
          close={() => setManual(null)}
          saved={(p) => {
            setProduct(p);
            setManual(null);
            setRun(null);
            setRefresh(refresh + 1);
          }}
        />
      )}
    </div>
  );
}
function ForecastDetail({ row: r }: { row: Forecast }) {
  const rows = [
    ...r.history.map((p) => ({
      month: p.month,
      actual: p.known ? p.actual : null,
      regular: p.known ? p.regular : null,
      forecast: null as number | null,
    })),
    ...r.forecast.map((p) => ({ month: p.month, actual: null, regular: null, forecast: p.quantity })),
  ];
  return (
    <div className="partner-forecast">
      <div className="partner-model">
        <Sparkles size={16} />
        <strong>{r.model || 'Недостаточно истории'}</strong>
      </div>
      <SalesChart rows={rows} />
      <div className="partner-quality">
        <div>
          <span>WAPE модели</span>
          <strong>
            {fmt(r.metrics?.wape)}
            {r.metrics?.wape == null ? '' : '%'}
          </strong>
        </div>
        <div>
          <span>WAPE среднего за 3 месяца</span>
          <strong>
            {fmt(r.baseline?.wape)}
            {r.baseline?.wape == null ? '' : '%'}
          </strong>
        </div>
        <div>
          <span>Период проверки</span>
          <strong className="partner-period">
            {r.holdout ? `${r.holdout.start} — ${r.holdout.end}` : 'Недостаточно истории'}
          </strong>
        </div>
      </div>
      {r.blocked.length ? (
        <div className="partner-missing">
          <strong>Для рекомендации количества нужно уточнить</strong>
          <ul>
            {r.blocked.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="partner-order">
          <span>Рекомендуем заказать</span>
          <strong>
            {fmt(r.quantity)} {r.unit}
          </strong>
          <p>{r.explanation}</p>
          <small>
            Сумма: {fmt(r.amount)} ₸ · Первый риск дефицита:{' '}
            {r.days_to_shortage == null ? 'не выявлен' : `через ${r.days_to_shortage} дн.`}
          </small>
        </div>
      )}
      <details className="partner-expand">
        <summary>Условия и ограничения прогноза</summary>
        <p>Источник: {r.source_basis}</p>
        <ul>
          {r.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
        <p>
          WAPE измеряет ошибку по зарегистрированным месячным отгрузкам. Неразмеченный упущенный спрос в эту
          метрику не входит. Сохранённый расчёт относится к версии входов на момент запуска.
        </p>
      </details>
    </div>
  );
}
function SalesChart({
  rows,
}: {
  rows: { month: string; actual: number | null; regular?: number | null; forecast?: number | null }[];
}) {
  if (!rows.length) return <p className="muted">В источниках нет месячной истории этой позиции.</p>;
  return (
    <div className="partner-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#ececf2" strokeDasharray="4 5" vertical={false} />
          <XAxis dataKey="month" tick={{ fontSize: 11 }} minTickGap={32} axisLine={false} tickLine={false} />
          <YAxis width={50} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
          <Tooltip formatter={(v) => fmt(Number(v))} />
          <Legend iconType="circle" />
          <Line dataKey="actual" name="Чистые продажи" stroke="#4098ff" dot={false} strokeWidth={2} />
          <Line dataKey="regular" name="Регулярный спрос" stroke="#aba1ee" dot={false} strokeWidth={1.5} />
          <Line
            dataKey="forecast"
            name="Прогноз"
            stroke="#7c65ff"
            dot={false}
            strokeWidth={2.5}
            strokeDasharray="5 3"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
