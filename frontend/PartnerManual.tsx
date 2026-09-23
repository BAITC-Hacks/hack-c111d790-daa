import { useRef, useEffect, useState, type FormEvent } from 'react';
import { X, Save } from 'lucide-react';
import { api } from './api';
import { type Product } from './partnerTypes';

type Props = {
  company: string;
  product: Product | null;
  snapshot: string;
  close: () => void;
  saved: (p: Product) => void;
};
export function PartnerManual({ company, product: p, snapshot, close, saved }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const numbers: [string, string, number, number, number][] = [
    ['stock', 'Свободный остаток', 0, 1e9, 0.001],
    ['purchase_price', 'Закупочная цена, ₸', 0, 1e9, 0.01],
    ['moq', 'Минимальный заказ (MOQ)', 1, 1e6, 1],
    ['pack_size', 'Кратность закупки', 1, 1e5, 1],
    ['lead_days', 'Срок поставки, дней', 1, 120, 1],
    ['review_days', 'Пересмотр, дней', 1, 60, 1],
    ['service_level', 'Уровень сервиса, %', 80, 99.5, 0.1],
    ['growth_pct', 'Дополнительный прирост, %', -80, 200, 0.1],
  ];
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const f = new FormData(e.currentTarget);
    const text = (key: string) => String(f.get(key) || '').trim();
    const lines = (key: string) =>
      text(key)
        .split('\n')
        .filter((x) => x.trim())
        .map((x) => x.split(';').map((v) => v.trim()));
    const numeric = (s: string) => {
      const n = Number(s.replace(',', '.'));
      if (!s || !Number.isFinite(n)) throw new Error('Проверьте числовые значения в таблицах.');
      return n;
    };
    try {
      const body: Record<string, unknown> = {
        expected_version: p?.version || null,
        sku: text('sku'),
        name: text('name'),
        unit: text('unit'),
        category: text('category') || null,
        supplier_sku: text('supplier_sku') || null,
        snapshot_date: text('snapshot_date'),
        stock_date: text('stock_date') || null,
        stock_scope_confirmed: f.has('stock_scope_confirmed'),
        note: text('note'),
      };
      for (const [key] of numbers)
        body[key] = text(key) === '' ? null : numeric(text(key)) / (key === 'service_level' ? 100 : 1);
      body.monthly_sales = lines('monthly_sales').map(([month, q, excluded, days, ...extra]) => {
        if (q === undefined || extra.length)
          throw new Error('Продажи: месяц; количество; исключено; дней отсутствия');
        return {
          month,
          quantity: q === '' ? null : numeric(q),
          excluded_quantity: excluded ? numeric(excluded) : 0,
          stockout_days: days ? numeric(days) : 0,
        };
      });
      body.inbound = lines('inbound').map(([eta, q, reference, ...extra]) => {
        if (!q || extra.length) throw new Error('Поступления: дата; количество; документ');
        return { eta, quantity: numeric(q), reference: reference || 'Ручное поступление' };
      });
      body.materials = lines('materials').map(([due_date, q, reference, ...extra]) => {
        if (!q || !reference || extra.length) throw new Error('Ведомость: дата; количество; ссылка');
        return { due_date, quantity: numeric(q), reference };
      });
      saved(await api<Product>(`/partners/${company}/manual`, body));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения');
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog ref={ref} className="modal wide partner-modal" onCancel={close}>
      <div className="modal-header">
        <h2>{p ? 'Ручной ввод · ' + p.sku : 'Новая позиция'}</h2>
        <button className="icon-button" onClick={close} aria-label="Закрыть">
          <X size={20} />
        </button>
      </div>
      <form onSubmit={(e) => void submit(e)}>
        <p className="muted">
          Пустое поле означает «неизвестно». Оригинальные файлы сохраняются; изменение получит автора «ручной
          ввод», время и вашу причину.
        </p>
        <div className="partner-fields">
          <label>
            Код 1С
            <input name="sku" required defaultValue={p?.sku} readOnly={!!p} />
          </label>
          <label>
            Наименование
            <input name="name" required defaultValue={p?.name} />
          </label>
          <label>
            Единица учёта
            <input name="unit" required defaultValue={p?.unit || ''} />
          </label>
          <label>
            Артикул поставщика
            <input name="supplier_sku" defaultValue={p?.supplier_sku || ''} />
          </label>
          <label>
            Категория
            <input name="category" defaultValue={p?.category || ''} />
          </label>
          <label>
            Дата расчёта
            <input name="snapshot_date" type="date" required defaultValue={p?.snapshot_date || snapshot} />
          </label>
          <label>
            Дата остатка
            <input name="stock_date" type="date" defaultValue={p?.stock_date || ''} />
          </label>
          {numbers.map(([key, label, min, max, step]) => (
            <label key={key}>
              {label}
              <input
                name={key}
                type="number"
                min={min}
                max={max}
                step={step}
                defaultValue={
                  p?.[key as keyof Product] == null
                    ? ''
                    : Number(p[key as keyof Product]) * (key === 'service_level' ? 100 : 1)
                }
                placeholder="Не указано"
              />
            </label>
          ))}
        </div>
        <label className="partner-check">
          <input type="checkbox" name="stock_scope_confirmed" defaultChecked={p?.stock_scope_confirmed} />
          Подтверждаю: продажи, свободный остаток и поступления относятся к одной области складов и одной
          единице учёта. Ведомость — дополнительный спрос, не учтённый в прогнозе.
        </label>
        <div className="partner-input-section">
          <h3>Месячные продажи</h3>
          <p>
            Одна строка: YYYY-MM; чистое количество со знаком; подтверждённый разовый объём; дней отсутствия.
            Пустое количество в существующей строке — нулевое движение в отчёте; удалённый месяц — неизвестное
            наблюдение. Неполный месяц расчёта не обучает модель.
          </p>
          <textarea
            name="monthly_sales"
            rows={9}
            aria-label="Месячные продажи"
            defaultValue={
              p?.monthly_sales
                .map(
                  (r) => `${r.month};${r.quantity ?? ''};${r.excluded_quantity || 0};${r.stockout_days || 0}`,
                )
                .join('\n') || ''
            }
          />
        </div>
        <div className="partner-fields two">
          <label>
            Поступления: YYYY-MM-DD; количество; документ
            <textarea
              name="inbound"
              rows={4}
              defaultValue={
                p?.inbound
                  .map((r) => `${r.eta || ''};${r.quantity};${r.reference.replaceAll(';', ',')}`)
                  .join('\n') || ''
              }
            />
          </label>
          <label>
            Материальная ведомость: YYYY-MM-DD; количество; ссылка
            <textarea
              name="materials"
              rows={4}
              defaultValue={
                p?.materials
                  .map((r) => `${r.due_date};${r.quantity};${r.reference.replaceAll(';', ',')}`)
                  .join('\n') || ''
              }
            />
          </label>
        </div>
        <label className="partner-note">
          Причина изменения
          <textarea
            name="note"
            required
            minLength={3}
            maxLength={500}
            rows={2}
            placeholder="Источник уточнения и что изменилось"
          />
        </label>
        {error && (
          <p className="error-banner" role="alert">
            {error}
          </p>
        )}
        <div className="partner-toolbar">
          <button type="button" className="button secondary" onClick={close}>
            Отмена
          </button>
          <button className="button primary" disabled={busy}>
            <Save size={16} />
            {busy ? 'Сохраняем…' : 'Сохранить изменения'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
