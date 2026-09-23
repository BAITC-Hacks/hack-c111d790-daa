export type Urgency = 'critical' | 'plan' | 'healthy';
export interface Metrics {
  wape: number | null;
  mae: number | null;
  bias: number | null;
  samples: number;
}
export interface Row {
  sku: string;
  name: string;
  warehouse: string;
  category: string;
  category_id: string;
  supplier: string;
  supplier_id: string;
  unit: string;
  price: number;
  quantity: number;
  amount: number;
  on_hand: number;
  inbound: number;
  late_inbound: number;
  overdue_inbound: number;
  material_demand: number;
  demand: number;
  safety_stock: number;
  net_need: number;
  lead_days: number;
  review_days: number;
  horizon: number;
  service_level: number;
  pack_size: number;
  moq: number;
  growth_pct: number;
  days_to_shortage: number | null;
  prearrival_shortage: number;
  urgency: Urgency;
  explanation: string;
  warnings: string[];
  excluded_units: number;
  lost_units: number;
  stockout_days: number;
  anomalies: { date: string; quantity: number; client_id: string; reason: string }[];
  model: string;
  model_name: string;
  trend_pct: number;
  raw_daily: number;
  cleaned_daily: number;
  restored_daily: number;
  forecast_daily: number;
  evaluation: Metrics;
  baseline: Metrics;
  confidence: string;
  holdout: { start: string; end: string } | null;
  candidates: { model: string; name: string; tuning_mae: number | null }[];
  folds: { train_end: string; test_start: string; test_end: string }[];
  history: { date: string; actual: number; regular: number; restored: number; stockout: boolean }[];
  forecast: { date: string; forecast: number; lower: number; upper: number }[];
  projection: { date: string; stock: number }[];
}
export interface Summary {
  positions: number;
  to_order: number;
  critical: number;
  total_amount: number;
  mean_wape: number | null;
  baseline_mean_wape: number | null;
  value_wape: number | null;
  baseline_value_wape: number | null;
  anomaly_events: number;
  excluded_by_unit: Record<string, number>;
  lost_by_unit: Record<string, number>;
}
export interface Run {
  id: string;
  created_at: string;
  as_of: string;
  synthetic: boolean;
  dataset_name: string;
  model_version: string;
  dataset_id: string;
  status: string;
  summary: Summary;
  rows: Row[];
  options: {
    warehouse: string | null;
    category_id: string | null;
    growth_adjustment_pct: number;
    review_days: number | null;
    service_level: number | null;
  };
  suppliers: { id: string; name: string; positions: number; amount: number; lead_days: number }[];
  approval: null | {
    at: string;
    note: string;
    amount: number;
    lines: { sku: string; warehouse: string; quantity: number }[];
  };
}
export interface Dataset {
  id: string;
  name: string;
  synthetic: boolean;
  as_of: string;
  history_start: string;
  sales_count: number;
  products_count: number;
  warehouses: string[];
  categories: { id: string; name: string; service_level: number; review_days: number }[];
  sources: Record<string, number>;
}
export interface RunEntry {
  id: string;
  created_at: string;
  status: string;
  summary: Summary;
}
