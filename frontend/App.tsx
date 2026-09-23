import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  ArrowDownToLine,
  ArrowUpRight,
  Bell,
  BookOpen,
  Boxes,
  Check,
  CheckCheck,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  Database,
  FileJson,
  FlaskConical,
  History,
  LayoutDashboard,
  LoaderCircle,
  Package,
  Play,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Truck,
  Upload,
  X,
} from 'lucide-react';
import { api } from './api';
import { PartnersWorkspace } from './PartnersWorkspace';
import { DemandChart } from './Chart';
import { StockOverview } from './StockOverview';
import type { Dataset, Row, Run, RunEntry, Urgency } from './types';

const num = (v: number, digits = 0) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(v);
const money = (v: number) => `${num(v)} ₸`;
const pct = (v: number | null) => (v === null ? '—' : `${num(v, 1)}%`);
const dateLabel = (d: string) =>
  new Date(d.length === 10 ? `${d}T12:00:00` : d).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
const rowKey = (r: { sku: string; warehouse: string }) => `${r.sku}:${r.warehouse}`;
const urgencyLabels = { critical: 'Риск дефицита', plan: 'К пополнению', healthy: 'В норме' };
const sourceLabels: Record<string, string> = {
  sales: 'История продаж',
  inventory: 'Остатки по складам',
  stockouts: 'Периоды отсутствия',
  inbound: 'Товары в пути',
  materials: 'Материальная ведомость',
  suppliers: 'Поставщики и сроки',
};

function Status({ value }: { value: Urgency }) {
  return (
    <span className={`status ${value}`}>
      <i />
      {urgencyLabels[value]}
    </span>
  );
}
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Package size={30} />
      <p>{children}</p>
    </div>
  );
}

function Modal({
  title,
  close,
  children,
  wide = false,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? 'modal wide' : 'modal'}
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div className="modal-header">
        <h2>{title}</h2>
        <button className="icon-button" onClick={close} aria-label="Закрыть">
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

export default function App() {
  const [dataset, setDataset] = useState<Dataset | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [page, setPage] = useState('partners');
  const [warehouse, setWarehouse] = useState('Алматы');
  const [category, setCategory] = useState('');
  const [supplier, setSupplier] = useState('');
  const [search, setSearch] = useState('');
  const [risk, setRisk] = useState('all');
  const [detail, setDetail] = useState<Row | null>(null);
  const [settings, setSettings] = useState(false);
  const [help, setHelp] = useState(false);
  const [approving, setApproving] = useState(false);
  const [growth, setGrowth] = useState(0);
  const [review, setReview] = useState('');
  const [service, setService] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [history, setHistory] = useState<RunEntry[]>([]);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [note, setNote] = useState('Проверены сроки поставок и рекомендованные количества.');
  const [confirmed, setConfirmed] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);

  async function task(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось выполнить запрос');
    } finally {
      setBusy('');
    }
  }
  const acceptRun = (result: Run) => {
    setRun(result);
    setDetail(null);
    setSupplier('');
    setRisk('all');
    setSearch('');
    setWarehouse(result.options.warehouse || '');
    setCategory(result.options.category_id || '');
    setGrowth(result.options.growth_adjustment_pct);
    setReview(result.options.review_days?.toString() || '');
    setService(result.options.service_level ? String(result.options.service_level * 100) : '');
  };
  useEffect(() => {
    if (page === 'partners' || dataset) return;
    void task('Подготавливаем прогноз…', async () => {
      const data = await api<Dataset>('/dataset');
      setDataset(data);
      const wh = data.warehouses.includes('Алматы') ? 'Алматы' : data.warehouses[0];
      const runs = await api<RunEntry[]>('/runs');
      if (runs.length) {
        const latest = await api<Run>(`/runs/${runs[0].id}`);
        if (latest.dataset_id === data.id) {
          acceptRun(latest);
          return;
        }
      }
      acceptRun(await api<Run>('/runs', { warehouse: wh }));
    });
  }, [page]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  const calculate = () =>
    task('Рассчитываем потребность…', async () => {
      acceptRun(
        await api<Run>('/runs', {
          warehouse: warehouse || null,
          category_id: category || null,
          growth_adjustment_pct: growth,
          review_days: review ? Number(review) : null,
          service_level: service ? Number(service) / 100 : null,
        }),
      );
      setSettings(false);
      setPage('dashboard');
      setToast('Расчёт готов. Откройте позицию, чтобы проверить обоснование.');
    });
  const navigate = (next: string) => {
    setPage(next);
    if (next === 'history')
      void task('Загружаем историю…', async () => setHistory(await api<RunEntry[]>('/runs')));
  };
  const startApproval = () => {
    if (!run) return;
    setQuantities(Object.fromEntries(run.rows.map((r) => [rowKey(r), r.quantity])));
    setConfirmed(false);
    setApproving(true);
  };
  const approve = () =>
    task('Сохраняем утверждение…', async () => {
      if (!run) return;
      const result = await api<Run>(`/runs/${run.id}/approve`, {
        confirmed,
        note,
        lines: run.rows.map((r) => ({ sku: r.sku, warehouse: r.warehouse, quantity: quantities[rowKey(r)] })),
      });
      setRun(result);
      setApproving(false);
      setToast('Заказ утверждён. CSV содержит согласованные количества.');
    });
  const importFile = async (file?: File) => {
    if (!file) return;
    await task('Проверяем и загружаем данные…', async () => {
      if (file.size > 32 * 1024 * 1024) throw new Error('Размер файла ограничен 32 МБ');
      await api('/dataset', JSON.parse(await file.text()));
      const data = await api<Dataset>('/dataset');
      setDataset(data);
      setRun(null);
      setWarehouse(data.warehouses[0]);
      setCategory('');
      setSupplier('');
      setGrowth(0);
      setReview('');
      setService('');
      setToast('Набор импортирован. Запустите новый расчёт.');
    });
    if (uploadRef.current) uploadRef.current.value = '';
  };
  const visible =
    run?.rows.filter(
      (r) =>
        (!supplier || r.supplier_id === supplier) &&
        (risk === 'all' || (risk === 'order' ? r.quantity > 0 : r.urgency === risk)) &&
        `${r.sku} ${r.name} ${r.supplier}`.toLowerCase().includes(search.toLowerCase()),
    ) || [];
  const featured = run?.rows.find((r) => r.sku === 'CBL-001') || run?.rows[0];
  const anomalies = run?.rows.reduce((sum, r) => sum + r.anomalies.length, 0) || 0;
  const pending =
    run &&
    (warehouse !== (run.options.warehouse || '') ||
      category !== (run.options.category_id || '') ||
      growth !== run.options.growth_adjustment_pct ||
      review !== (run.options.review_days?.toString() || '') ||
      service !== (run.options.service_level ? String(run.options.service_level * 100) : ''));

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate('dashboard');
          }}
        >
          <span className="brand-icon">
            <Boxes size={23} />
          </span>
          <span className="brand-name">
            <strong>Контур</strong>
            <small>Электрокомплект</small>
          </span>
        </a>
        <p className="nav-label">Рабочее пространство</p>
        <nav>
          {[
            { id: 'partners', label: 'Данные партнёров', icon: FileJson },
            { id: 'dashboard', label: 'Демо · обзор закупок', icon: LayoutDashboard },
            { id: 'orders', label: 'Рекомендации', icon: ClipboardCheck },
            { id: 'quality', label: 'Качество прогноза', icon: FlaskConical },
            { id: 'data', label: 'Источники данных', icon: Database },
            { id: 'history', label: 'История расчётов', icon: History },
          ].map((n) => (
            <button
              key={n.id}
              aria-label={n.label}
              title={n.label}
              className={`nav-item ${page === n.id ? 'active' : ''}`}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={18} />
              {n.label}
              {n.id === 'orders' && run && <span className="nav-count">{run.summary.to_order}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button className="nav-item" onClick={() => setHelp(true)}>
            <CircleHelp size={18} />О методологии
          </button>
          <div className="profile">
            <span>МЗ</span>
            <div>
              <strong>Менеджер закупок</strong>
              <small>Локальная демоверсия</small>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Рабочее пространство <ChevronRight size={14} />
            <span>
              {page === 'partners'
                ? 'Данные партнёров'
                : page === 'dashboard'
                  ? 'Обзор'
                  : page === 'orders'
                    ? 'Рекомендации'
                    : page === 'quality'
                      ? 'Качество прогноза'
                      : page === 'data'
                        ? 'Данные'
                        : 'История'}
            </span>
          </div>
          <div className="topbar-right">
            <span className="environment">
              <i />
              {page === 'partners'
                ? 'IEK / Systeme · исходные файлы'
                : dataset?.synthetic
                  ? 'Синтетические данные'
                  : 'Импортированные данные'}
            </span>
            <button
              className="icon-button"
              aria-label="Показать риски дефицита"
              onClick={() => {
                setPage('orders');
                setRisk('critical');
              }}
            >
              <Bell size={18} />
              {!!run?.summary.critical && <i className="notification-dot" />}
            </button>
            <span className="mini-avatar">МЗ</span>
          </div>
        </header>
        <main>
          {page === 'partners' && <PartnersWorkspace />}
          {page !== 'partners' && (
            <>
              <div className="page-heading">
                <div>
                  <h1>
                    {page === 'dashboard'
                      ? 'Обзор закупок'
                      : page === 'orders'
                        ? 'Рекомендации к закупке'
                        : page === 'quality'
                          ? 'Качество прогноза'
                          : page === 'data'
                            ? 'Источники данных'
                            : 'История решений'}
                  </h1>
                  <p>
                    {page === 'dashboard'
                      ? 'Прогноз спроса и рекомендации по пополнению склада.'
                      : page === 'orders'
                        ? 'Проверьте позиции, скорректируйте количества и утвердите заказ.'
                        : page === 'quality'
                          ? 'Реальные метрики на отложенном периоде, отдельно от выбора модели.'
                          : page === 'data'
                            ? 'Единый контракт для продаж, остатков и поставок.'
                            : 'Сохранённые расчёты, параметры и ручные утверждения.'}
                  </p>
                </div>
                <div className="heading-actions">
                  <button className="button secondary" onClick={() => setSettings(true)} disabled={!!busy}>
                    <Settings2 size={16} />
                    Параметры
                  </button>
                  <button
                    className="button primary"
                    onClick={() => void calculate()}
                    disabled={!!busy || !dataset}
                  >
                    {busy ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}Рассчитать
                    заказ
                  </button>
                </div>
              </div>
              {error && (
                <div role="alert" className="error-banner">
                  <strong>Не удалось выполнить действие.</strong> {error}
                  <button onClick={() => setError('')} aria-label="Скрыть ошибку">
                    <X size={16} />
                  </button>
                </div>
              )}
              {busy && (
                <div className="busy-banner" role="status">
                  <LoaderCircle className="spin" size={15} />
                  {busy}
                </div>
              )}
              <div className="scope-bar">
                <div className="scope-input">
                  <Boxes size={16} />
                  <select aria-label="Склад" value={warehouse} onChange={(e) => setWarehouse(e.target.value)}>
                    <option value="">Все склады</option>
                    {dataset?.warehouses.map((w) => (
                      <option key={w}>{w}</option>
                    ))}
                  </select>
                </div>
                <div className="scope-input">
                  <select
                    aria-label="Категория расчёта"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="">Все категории</option>
                    {dataset?.categories.map((c) => (
                      <option value={c.id} key={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="scope-date">
                  {dataset && (
                    <>
                      Срез данных <strong>{dateLabel(dataset.as_of)}</strong>
                    </>
                  )}
                </div>
                <span className="scope-status">
                  {pending ? (
                    <>
                      <i className="pending-dot" />
                      Параметры изменены — пересчитайте
                    </>
                  ) : run ? (
                    <>
                      <CheckCheck size={15} />
                      Расчёт сохранён · {run.id.slice(0, 6)}
                    </>
                  ) : (
                    'Запустите расчёт'
                  )}
                </span>
              </div>
            </>
          )}
          {page === 'dashboard' && run && (
            <>
              <div className="overview-grid">
                <section className="panel demand-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Динамика спроса</h2>
                      <p>
                        {featured?.name} <span className="inline-code">{featured?.sku}</span>
                      </p>
                    </div>
                    <button className="text-button" onClick={() => featured && setDetail(featured)}>
                      Подробнее <ArrowUpRight size={15} />
                    </button>
                  </div>
                  {featured && <DemandChart row={featured} />}
                </section>
                <StockOverview run={run} onOpen={() => setPage('orders')} />
              </div>
              <div className="metrics-grid">
                <Metric
                  title="К пополнению"
                  value={`${run.summary.to_order}`}
                  unit="позиций"
                  icon={<Package size={19} />}
                  footer={`из ${run.summary.positions} позиций SKU × склад`}
                  onClick={() => {
                    setPage('orders');
                    setRisk('order');
                  }}
                />
                <Metric
                  title="Требуют внимания"
                  value={`${run.summary.critical}`}
                  unit="позиций"
                  icon={<Truck size={19} />}
                  tone="orange"
                  footer="Риск дефицита до новой поставки"
                  onClick={() => {
                    setPage('orders');
                    setRisk('critical');
                  }}
                />
                <Metric
                  title="Рекомендуемая закупка"
                  value={num(run.summary.total_amount / 1e6, 2)}
                  unit="млн ₸"
                  icon={<Boxes size={19} />}
                  footer={`${run.suppliers.length} поставщика · с учётом партий`}
                  onClick={() => setPage('orders')}
                />
                <Metric
                  title="WAPE · по стоимости"
                  value={pct(run.summary.value_wape)}
                  icon={<TrendingUp size={19} />}
                  footer={`Baseline: ${pct(run.summary.baseline_value_wape)} · ниже лучше`}
                  onClick={() => setPage('quality')}
                />
              </div>
            </>
          )}

          {(page === 'dashboard' || page === 'orders') && run && (
            <section className="panel recommendations">
              <div className="panel-heading">
                <div className="section-title">
                  <h2>Рекомендации к закупке</h2>
                  <span className="count-pill">{run.summary.to_order}</span>
                  <span className={`draft-label ${run.status}`}>
                    {run.status === 'approved' ? 'Утверждено' : 'На проверке'}
                  </span>
                </div>
                <div className="table-actions">
                  <a className="button ghost" href={`/api/runs/${run.id}/export`}>
                    <ArrowDownToLine size={15} />
                    Экспорт CSV
                  </a>
                  <button
                    className="button primary small"
                    onClick={startApproval}
                    disabled={!!busy || run.status === 'approved' || !run.summary.to_order || !!pending}
                  >
                    <Check size={16} />
                    {run.status === 'approved' ? 'Заказ утверждён' : 'Проверить заказ'}
                  </button>
                </div>
              </div>
              <div className="table-filters">
                <div className="filter-tabs">
                  {[
                    { id: 'all', label: 'Все позиции' },
                    { id: 'critical', label: 'Риск дефицита' },
                    { id: 'order', label: 'К пополнению' },
                  ].map((t) => (
                    <button
                      className={risk === t.id ? 'active' : ''}
                      key={t.id}
                      onClick={() => setRisk(t.id)}
                    >
                      {t.label}
                      {t.id === 'critical' && <span>{run.summary.critical}</span>}
                    </button>
                  ))}
                </div>
                <div className="table-search">
                  <Search size={15} />
                  <input
                    aria-label="Поиск по товарам"
                    placeholder="Найти товар или артикул…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                <select
                  className="supplier-select"
                  aria-label="Поставщик"
                  value={supplier}
                  onChange={(e) => setSupplier(e.target.value)}
                >
                  <option value="">Все поставщики</option>
                  {run.suppliers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div className="table-scroll">
                <table className="order-table">
                  <thead>
                    <tr>
                      <th>Товар / артикул</th>
                      <th>Поставщик</th>
                      <th>Остаток / в пути</th>
                      <th>К заказу</th>
                      <th>Сумма</th>
                      <th>Приоритет</th>
                      <th aria-label="Подробности" />
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((r) => (
                      <tr key={rowKey(r)} onClick={() => setDetail(r)}>
                        <td>
                          <button
                            className="product-name"
                            onClick={(e) => {
                              e.stopPropagation();
                              setDetail(r);
                            }}
                          >
                            {r.name}
                          </button>
                          <div className="product-meta">
                            {r.sku}
                            <span>·</span>
                            {r.warehouse}
                          </div>
                        </td>
                        <td>
                          <strong className="supplier-name">{r.supplier}</strong>
                          <small>{r.lead_days} дней поставка</small>
                        </td>
                        <td>
                          <span className="stock-value">
                            {num(r.on_hand)} <span>/ {num(r.inbound)}</span>
                          </span>
                          <small>{r.unit}</small>
                        </td>
                        <td>
                          <strong className="order-quantity">
                            {num(
                              run.approval?.lines.find((l) => rowKey(l) === rowKey(r))?.quantity ??
                                r.quantity,
                            )}{' '}
                            <span>{r.unit}</span>
                          </strong>
                          <small>
                            {run.status === 'approved' ? 'Утверждено' : `Партия ${r.pack_size} ${r.unit}`}
                          </small>
                        </td>
                        <td className="amount">
                          {money(
                            (run.approval?.lines.find((l) => rowKey(l) === rowKey(r))?.quantity ??
                              r.quantity) * r.price,
                          )}
                        </td>
                        <td>
                          <Status value={r.urgency} />
                        </td>
                        <td>
                          <ChevronRight size={16} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!visible.length && (
                <Empty>По этим условиям ничего не найдено. Измените поиск или фильтры.</Empty>
              )}
              <div className="table-footer">
                <span>
                  Показано {visible.length} из {run.rows.length} позиций
                </span>
                <span>
                  <i className="live-dot" />
                  Нажмите на товар, чтобы увидеть обоснование
                </span>
              </div>
            </section>
          )}

          {(page === 'dashboard' || page === 'orders') && !run && !busy && (
            <section className="panel">
              <Empty>Данные готовы. Нажмите «Рассчитать заказ».</Empty>
            </section>
          )}
          {page === 'orders' && run && (
            <div className="supplier-grid">
              {run.suppliers.map((s) => (
                <button className="supplier-card" key={s.id} onClick={() => setSupplier(s.id)}>
                  <Truck size={20} />
                  <strong>{s.name}</strong>
                  <span>
                    {s.positions} позиций · {s.lead_days} дн.
                  </span>
                  <b>{money(s.amount)}</b>
                  <small>По исходной рекомендации</small>
                </button>
              ))}
            </div>
          )}

          {page === 'quality' && run && (
            <>
              <div className="method-banner">
                <FlaskConical size={25} />
                <div>
                  <h2>Сначала проверка на прошлом. Затем прогноз.</h2>
                  <p>
                    Два временных среза по 28 дней выбирают модель. Последние 28 дней — отдельный holdout.
                    WAPE оценивается на днях наличия, после исключения проектных продаж.
                  </p>
                </div>
                <span className="version-tag">{run.model_version}</span>
              </div>
              <div className="metrics-grid three">
                <Metric
                  title="WAPE · по закупочной стоимости"
                  value={pct(run.summary.value_wape)}
                  icon={<FlaskConical size={20} />}
                  footer={`Среднее по SKU × склад: ${pct(run.summary.mean_wape)}`}
                />
                <Metric
                  title="Baseline · сырое среднее 56 дней"
                  value={pct(run.summary.baseline_value_wape)}
                  icon={<TrendingUp size={20} />}
                  footer={`Среднее по SKU × склад: ${pct(run.summary.baseline_mean_wape)}`}
                />
                <Metric
                  title="Исключено клиент-дней"
                  value={String(anomalies)}
                  icon={<ShieldCheck size={20} />}
                  footer="Агрегация накладных одного клиента за день"
                />
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Качество по каждой позиции</h2>
                  <span className="muted">Меньшая ошибка — лучше</span>
                </div>
                <div className="table-scroll">
                  <table className="order-table">
                    <thead>
                      <tr>
                        <th>Товар</th>
                        <th>Выбранная модель</th>
                        <th>WAPE</th>
                        <th>Baseline</th>
                        <th>Смещение</th>
                        <th>Дни оценки</th>
                      </tr>
                    </thead>
                    <tbody>
                      {run.rows.map((r) => (
                        <tr key={rowKey(r)} onClick={() => setDetail(r)}>
                          <td>
                            <button className="product-name" onClick={() => setDetail(r)}>
                              {r.name}
                            </button>
                            <small>{r.warehouse}</small>
                          </td>
                          <td>{r.model_name}</td>
                          <td>
                            <b
                              className={
                                r.evaluation.wape !== null && r.evaluation.wape > 40
                                  ? 'warning-text'
                                  : 'green-text'
                              }
                            >
                              {pct(r.evaluation.wape)}
                            </b>
                          </td>
                          <td>{pct(r.baseline.wape)}</td>
                          <td>{pct(r.evaluation.bias)}</td>
                          <td>{r.evaluation.samples} / 28</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              <p className="footnote">
                Синтетический backtest не доказывает качество на данных партнёра. Полоса прогноза — ориентир
                по абсолютным ошибкам holdout, а не гарантия уровня сервиса. Восстановленный упущенный спрос
                не входит в фактическую метрику.
              </p>
            </>
          )}
          {page === 'quality' && !run && <Empty>Для оценки качества сначала запустите расчёт.</Empty>}

          {page === 'data' && dataset && (
            <>
              <section className="data-hero panel">
                <div className="data-hero-icon">
                  <Database size={30} />
                </div>
                <div>
                  <span className="eyebrow">
                    {dataset.synthetic ? 'ВОСПРОИЗВОДИМОЕ ДЕМО · SEED 42' : 'ЗАГРУЖЕННЫЙ НАБОР'}
                  </span>
                  <h2>{dataset.name}</h2>
                  <p>
                    {dateLabel(dataset.history_start)} — {dateLabel(dataset.as_of)} ·{' '}
                    {num(dataset.sales_count)} продаж · {dataset.products_count} SKU
                  </p>
                </div>
                <a className="button secondary" href="/api/dataset/download">
                  <ArrowDownToLine size={16} />
                  Скачать JSON
                </a>
              </section>
              <div className="source-grid">
                {Object.entries(dataset.sources).map(([key, count]) => (
                  <div className="source-card" key={key}>
                    <span className="source-icon">
                      {key === 'sales' ? (
                        <TrendingUp size={20} />
                      ) : key === 'inbound' ? (
                        <Truck size={20} />
                      ) : (
                        <Database size={20} />
                      )}
                    </span>
                    <h3>{sourceLabels[key]}</h3>
                    <b>{num(count)}</b>
                    <span>записей</span>
                    <div>
                      <Check size={14} />
                      Структура проверена
                    </div>
                  </div>
                ))}
              </div>
              <section className="panel import-panel">
                <FileJson size={33} />
                <h2>Подключите свой набор данных</h2>
                <p>
                  Загрузите JSON по контракту API. Клиенты — только с обезличенными ID вида{' '}
                  <code>anon_…</code>.<br />
                  Для CSV-выгрузок предусмотрен адаптер в репозитории.
                </p>
                <input
                  ref={uploadRef}
                  type="file"
                  accept="application/json,.json"
                  aria-label="Импорт набора JSON"
                  onChange={(e) => void importFile(e.target.files?.[0])}
                  hidden
                />
                <div>
                  <button
                    className="button primary"
                    disabled={!!busy}
                    onClick={() => uploadRef.current?.click()}
                  >
                    <Upload size={16} />
                    Импортировать JSON
                  </button>
                  <a className="button secondary" href="/api/dataset/schema" target="_blank" rel="noreferrer">
                    JSON Schema <ArrowUpRight size={15} />
                  </a>
                </div>
              </section>
              <div className="footnote">
                <ShieldCheck size={16} />
                Все вычисления выполняются локально. Продажи не отправляются во внешнюю ИИ-модель. Проверка
                формата ID не заменяет анонимизацию у источника.
              </div>
            </>
          )}

          {page === 'history' && (
            <section className="panel">
              <div className="panel-heading">
                <h2>Сохранённые расчёты</h2>
                <span className="muted">Последние 30</span>
              </div>
              {history.length ? (
                <div className="table-scroll">
                  <table className="order-table">
                    <thead>
                      <tr>
                        <th>Расчёт</th>
                        <th>Создан</th>
                        <th>Позиций к закупке</th>
                        <th>Рекомендованная сумма</th>
                        <th>Статус</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((h) => (
                        <tr
                          key={h.id}
                          onClick={() =>
                            void task('Открываем расчёт…', async () => {
                              acceptRun(await api<Run>(`/runs/${h.id}`));
                              setPage('orders');
                            })
                          }
                        >
                          <td>
                            <button className="product-name">#{h.id.slice(0, 8)}</button>
                          </td>
                          <td>
                            {dateLabel(h.created_at)}{' '}
                            <small>{new Date(h.created_at).toLocaleTimeString('ru')}</small>
                          </td>
                          <td>{h.summary.to_order}</td>
                          <td>{money(h.summary.total_amount)}</td>
                          <td>
                            <span className={`draft-label ${h.status}`}>
                              {h.status === 'approved' ? 'Утверждено' : 'Черновик'}
                            </span>
                          </td>
                          <td>
                            <ArrowUpRight size={16} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty>Расчётов пока нет.</Empty>
              )}
            </section>
          )}
          <footer className="page-footer">
            <span>
              КОНТУР <span>×</span> ЭЛЕКТРОКОМПЛЕКТ
            </span>
            <span>HACKALEM AI · Решения на основе данных</span>
          </footer>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <CheckCheck size={19} />
          {toast}
        </div>
      )}
      {detail && (
        <Modal title="Обоснование рекомендации" close={() => setDetail(null)} wide>
          <Detail row={detail} />
        </Modal>
      )}
      {settings && (
        <Modal title="Параметры нового расчёта" close={() => setSettings(false)}>
          <form
            className="settings-form"
            onSubmit={(e) => {
              e.preventDefault();
              void calculate();
            }}
          >
            <p>
              Категория задаёт период пересмотра и уровень сервиса. Здесь можно проверить альтернативный
              сценарий.
            </p>
            <label>
              Дополнительный прирост спроса, %
              <input
                type="number"
                min="-80"
                max="200"
                value={growth}
                onChange={(e) => setGrowth(Number(e.target.value))}
              />
              <small>Применяется поверх прогноза и прироста из карточки SKU.</small>
            </label>
            <label>
              Период пересмотра, дней
              <input
                type="number"
                min="1"
                max="60"
                placeholder="По политике категории"
                value={review}
                onChange={(e) => setReview(e.target.value)}
              />
            </label>
            <label>
              Целевой уровень сервиса, %
              <input
                type="number"
                min="80"
                max="99.5"
                step="0.1"
                placeholder="По политике категории"
                value={service}
                onChange={(e) => setService(e.target.value)}
              />
              <small>Используется для приближённого страхового запаса; не является гарантией.</small>
            </label>
            <button className="button primary" disabled={!!busy}>
              <Play size={16} />
              Рассчитать сценарий
            </button>
          </form>
        </Modal>
      )}
      {help && (
        <Modal title="Как работает Контур" close={() => setHelp(false)}>
          <div className="help-content">
            {[
              [
                '01',
                'Сначала данные',
                'Продажи, остатки, дни отсутствия, поставки с ETA, политика категории и дополнительная потребность из 1С.',
              ],
              [
                '02',
                'Отделяем регулярный спрос',
                'Суммируем накладные клиента за день, находим редкие крупные заказы по устойчивому порогу median/MAD. Дни stockout исключаем из обучения.',
              ],
              [
                '03',
                'Выбираем прогноз по backtest',
                'Huber с годовой и недельной сезонностью и трендом, недельный профиль, среднее или Croston SBA для редкого спроса. Выбор — по MAE на временных срезах.',
              ],
              [
                '04',
                'Переводим прогноз в заказ',
                'Спрос на срок поставки + период пересмотра, страховой запас и ведомость. Вычитаем остаток и подтверждённые поступления. Округляем по MOQ и партии.',
              ],
              [
                '05',
                'Решение принимает менеджер',
                'Проверяете обоснование, редактируете количества, утверждаете. Сохраняются версия модели, данные и комментарий. Экспорт CSV — отдельное действие.',
              ],
            ].map(([n, title, description]) => (
              <div className="method-step" key={n}>
                <span>{n}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </div>
              </div>
            ))}
            <a
              className="button secondary"
              href="http://127.0.0.1:8000/docs"
              target="_blank"
              rel="noreferrer"
            >
              <BookOpen size={16} />
              Документация API
            </a>
          </div>
        </Modal>
      )}
      {approving && run && (
        <Modal title="Проверка и утверждение заказа" close={() => setApproving(false)} wide>
          <div className="approval-content">
            <p className="muted">
              Все количества можно изменить. Ноль исключает позицию. Учитывайте минимальную партию и кратность
              упаковки.
            </p>
            <div className="approval-table">
              <table className="order-table">
                <thead>
                  <tr>
                    <th>Позиция</th>
                    <th>Рекомендация</th>
                    <th>Утвердить</th>
                    <th>Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {run.rows.map((r) => (
                    <tr key={rowKey(r)}>
                      <td>
                        <strong>{r.name}</strong>
                        <small>
                          {r.warehouse} · {r.supplier} · MOQ {r.moq}, партия {r.pack_size}
                        </small>
                      </td>
                      <td>
                        {num(r.quantity)} {r.unit}
                      </td>
                      <td>
                        <input
                          aria-label={`Количество ${r.sku} ${r.warehouse}`}
                          className="quantity-input"
                          type="number"
                          min="0"
                          max="1000000000"
                          step={r.pack_size}
                          value={quantities[rowKey(r)] ?? 0}
                          onChange={(e) =>
                            setQuantities({ ...quantities, [rowKey(r)]: Number(e.target.value) })
                          }
                        />
                      </td>
                      <td>{money((quantities[rowKey(r)] || 0) * r.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="approval-total">
              Итого к утверждению{' '}
              <strong>
                {money(run.rows.reduce((s, r) => s + (quantities[rowKey(r)] || 0) * r.price, 0))}
              </strong>
            </div>
            <label className="note-label">
              Комментарий ответственного сотрудника
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                minLength={3}
                maxLength={500}
              />
            </label>
            <label className="confirm-check">
              <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />Я
              проверил количества и сроки и подтверждаю этот заказ.
            </label>
            {error && (
              <p role="alert" className="warning-text">
                {error}
              </p>
            )}
            <div className="approval-actions">
              <span>
                <ShieldCheck size={15} />
                Утверждение сохраняется в журнале
              </span>
              <button
                className="button primary"
                disabled={!confirmed || note.trim().length < 3 || !!busy}
                onClick={() => void approve()}
              >
                <Check size={17} />
                Утвердить заказ
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Metric({
  title,
  value,
  unit,
  icon,
  footer,
  tone = '',
  onClick,
}: {
  title: string;
  value: string;
  unit?: string;
  icon: ReactNode;
  footer: string;
  tone?: string;
  onClick?: () => void;
}) {
  return (
    <button className={`metric-card ${tone}`} onClick={onClick} disabled={!onClick}>
      <div className="metric-head">
        <span className="metric-icon">{icon}</span>
        {onClick && <ArrowUpRight size={16} />}
      </div>
      <div className="metric-title">{title}</div>
      <div className="metric-value">
        {value} <small>{unit}</small>
      </div>
      <div className="metric-footer">{footer}</div>
    </button>
  );
}

function Detail({ row: r }: { row: Row }) {
  return (
    <div className="detail-content">
      <div className="detail-title">
        <div>
          <span className="eyebrow">
            {r.sku} · {r.warehouse}
          </span>
          <h2>{r.name}</h2>
          <p>
            {r.supplier} · {r.category}
          </p>
        </div>
        <Status value={r.urgency} />
      </div>
      <div className="detail-callout">
        <div>
          <span>Рекомендуем заказать</span>
          <strong>
            {num(r.quantity)} <small>{r.unit}</small>
          </strong>
        </div>
        <div>
          <span>Сумма закупки</span>
          <b>{money(r.amount)}</b>
        </div>
        <div>
          <span>Горизонт покрытия</span>
          <b>{r.horizon} дней</b>
          <small>
            {r.lead_days} поставка + {r.review_days} пересмотр
          </small>
        </div>
      </div>
      <h3>Как получилось это количество</h3>
      <div className="formula-grid">
        {[
          ['Спрос', r.demand, '+'],
          ['Страховой запас', r.safety_stock, '+'],
          ['Ведомость 1С', r.material_demand, '−'],
          ['Остаток', r.on_hand, '−'],
          ['В пути', r.inbound, '='],
          ['Потребность', r.net_need, ''],
        ].map(([label, value, sign]) => (
          <div key={String(label)}>
            <span>{label}</span>
            <strong>{num(Number(value), 1)}</strong>
            <i>{sign}</i>
          </div>
        ))}
      </div>
      <p className="explanation">{r.explanation}</p>
      <div className="factor-chips">
        <span>
          Рост по сценарию: {r.growth_pct > 0 ? '+' : ''}
          {r.growth_pct}%
        </span>
        <span>Сервис: {num(r.service_level * 100, 1)}%</span>
        <span>
          Партия: {r.pack_size} {r.unit}
        </span>
      </div>
      {r.warnings.map((w) => (
        <div className="detail-warning" key={w}>
          <CircleHelp size={16} />
          {w}
        </div>
      ))}
      <div className="detail-chart-heading">
        <h3>История и прогноз спроса</h3>
        <span className="model-chip">{r.model_name}</span>
      </div>
      <DemandChart row={r} expanded />
      <p className="footnote">
        Полоса неопределённости построена по ошибкам holdout и не является гарантированным интервалом.
        Историческое восстановление stockout — оценка модели.
      </p>
      <div className="detail-facts">
        <div>
          <span>Продажи / день, сырые</span>
          <b>
            {num(r.raw_daily, 1)} {r.unit}
          </b>
        </div>
        <div>
          <span>После выбросов / день</span>
          <b>
            {num(r.cleaned_daily, 1)} {r.unit}
          </b>
        </div>
        <div>
          <span>С учётом stockout / день</span>
          <b>
            {num(r.restored_daily, 1)} {r.unit}
          </b>
        </div>
        <div>
          <span>Прогноз / день</span>
          <b>
            {num(r.forecast_daily, 1)} {r.unit}
          </b>
        </div>
      </div>
      <h3>Проверка прогноза</h3>
      <div className="detail-facts">
        <div>
          <span>WAPE · holdout</span>
          <b>{pct(r.evaluation.wape)}</b>
        </div>
        <div>
          <span>Baseline WAPE</span>
          <b>{pct(r.baseline.wape)}</b>
        </div>
        <div>
          <span>Упущенный спрос · история</span>
          <b>
            {num(r.lost_units)} {r.unit}
          </b>
        </div>
        <div>
          <span>Дней отсутствия</span>
          <b>{r.stockout_days}</b>
        </div>
      </div>
      {r.holdout && (
        <p className="muted">
          Holdout: {dateLabel(r.holdout.start)} — {dateLabel(r.holdout.end)}. Дней оценки:{' '}
          {r.evaluation.samples}.
        </p>
      )}
      <details>
        <summary>Сравнение моделей и аномальные продажи</summary>
        <div className="candidate-list">
          {r.candidates.map((c) => (
            <div key={c.model}>
              <span>
                {c.name}
                {c.model === r.model && ' ✓'}
              </span>
              <b>MAE {c.tuning_mae === null ? '—' : num(c.tuning_mae, 2)}</b>
            </div>
          ))}
        </div>
        <p className="footnote">
          MAE — на срезах выбора модели. Для прерывистого спроса выбор ограничен средним и Croston SBA.
        </p>
        {r.anomalies.length ? (
          r.anomalies.map((a, i) => (
            <div className="anomaly-line" key={i}>
              <span>
                {dateLabel(a.date)} · {a.client_id}
              </span>
              <b>
                {num(a.quantity)} {r.unit}
              </b>
            </div>
          ))
        ) : (
          <p className="muted">Редкие крупные продажи не обнаружены.</p>
        )}
      </details>
    </div>
  );
}
