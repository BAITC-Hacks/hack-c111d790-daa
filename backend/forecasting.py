"""CPU forecasting; tuning folds and final holdout strictly respect event time."""

import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor

from .schemas import Sale, Stockout

MODEL_VERSION = "demand-1.0.0"
MODEL_NAMES = {
    "huber": "Huber · сезонность + тренд",
    "weekday": "Недельный профиль",
    "mean": "Среднее доступных дней",
    "sba": "Croston SBA · редкий спрос",
}


@dataclass
class Series:
    dates: list[date]
    raw: np.ndarray
    available: np.ndarray
    customer_days: list[tuple[int, str, float]]


def build_series(sales: list[Sale], stockouts: list[Stockout], start: date, as_of: date) -> Series:
    n = (as_of - start).days
    raw = np.zeros(n)
    available = np.ones(n, dtype=bool)
    grouped: dict[tuple[int, str], float] = defaultdict(float)
    for s in sales:
        i = (s.date - start).days
        raw[i] += s.quantity
        grouped[i, s.client_id] += s.quantity
    for s in stockouts:
        available[(s.start - start).days : (s.end - start).days + 1] = False
    return Series(
        [start + timedelta(days=i) for i in range(n)],
        raw,
        available,
        [(i, client, q) for (i, client), q in grouped.items()],
    )


def clean(series: Series, train_end: int) -> tuple[np.ndarray, list[dict], float]:
    """Learn a robust threshold on the training prefix, never on validation future.

    Frequent large orders remain regular demand. Split invoices are aggregated
    per SKU/warehouse/customer/day before applying the threshold.
    """
    history = [q for i, _, q in series.customer_days if i < train_end]
    if len(history) < 14:
        return series.raw.copy(), [], float("inf")
    values = np.asarray(history)
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    threshold = max(median * 8, median + 8 * 1.4826 * mad, float(np.quantile(values, 0.9)) * 4, 10)
    large_frequency: dict[str, int] = defaultdict(int)
    for i, client, q in series.customer_days:
        if i < train_end and q > threshold:
            large_frequency[client] += 1
    result = series.raw.copy()
    anomalies = []
    for i, client, q in series.customer_days:
        if q > threshold and large_frequency[client] <= max(3, train_end // 90):
            result[i] -= q
            anomalies.append(
                dict(
                    date=series.dates[i].isoformat(),
                    quantity=q,
                    client_id=client,
                    reason="Редкая крупная продажа клиенту за день",
                )
            )
    return np.maximum(result, 0), anomalies, threshold


def features(dates: list[date], origin: date, annual: bool) -> np.ndarray:
    t = np.array([(d - origin).days / 365.25 for d in dates])
    columns = [t]
    if annual:
        for k in [1, 2]:
            columns.extend([np.sin(2 * np.pi * k * t), np.cos(2 * np.pi * k * t)])
    weekdays = np.array([d.weekday() for d in dates])
    columns.extend([(weekdays == k).astype(float) for k in range(6)])
    return np.column_stack(columns)


def predict(
    model: str, dates: list[date], y: np.ndarray, available: np.ndarray, future: list[date]
) -> np.ndarray:
    if not len(future):
        return np.zeros(0)
    valid = available & np.isfinite(y)
    if not valid.any():
        return np.zeros(len(future))
    recent_mask = valid.copy()
    recent_mask[:-56] = False
    recent = y[recent_mask] if recent_mask.any() else y[valid]
    average = float(np.mean(recent))
    if model == "mean":
        return np.full(len(future), average)
    if model == "weekday":
        return np.array(
            [
                float(
                    np.mean(
                        [
                            y[i]
                            for i in range(max(0, len(y) - 56), len(y))
                            if valid[i] and dates[i].weekday() == d.weekday()
                        ]
                    )
                )
                if any(
                    valid[i] and dates[i].weekday() == d.weekday() for i in range(max(0, len(y) - 56), len(y))
                )
                else average
                for d in future
            ]
        )
    if model == "sba":
        # Time advances only on days with availability; stockouts are censored.
        observed = y[valid]
        indices = np.flatnonzero(observed > 0)
        if len(indices) < 2:
            return np.full(len(future), average)
        alpha, demand, interval = 0.15, float(observed[indices[0]]), float(indices[0] + 1)
        last = indices[0]
        for i in indices[1:]:
            demand += alpha * (observed[i] - demand)
            interval += alpha * (i - last - interval)
            last = i
        return np.full(len(future), (1 - alpha / 2) * demand / max(interval, 1))
    if valid.sum() < 28 or np.max(y[valid]) == 0:
        return np.full(len(future), average)
    annual = len(y) >= 400
    x = features(dates, dates[0], annual)
    future_x = features(future, dates[0], annual)
    scale = max(float(np.mean(y[valid])), 1)
    reg = HuberRegressor(epsilon=1.5, alpha=0.2, max_iter=500, tol=1e-5)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            reg.fit(x[valid], y[valid] / scale)
        result = reg.predict(future_x) * scale
        return np.clip(result, 0, max(float(np.quantile(y[valid], 0.95)) * 5, 1))
    except (ValueError, ConvergenceWarning):
        return np.full(len(future), average)


def metric(actual: np.ndarray, forecast: np.ndarray) -> dict:
    if len(actual) == 0:
        return dict(wape=None, mae=None, bias=None, samples=0, actual_sum=0.0, absolute_error_sum=0.0)
    denominator = float(np.sum(actual))
    return dict(
        wape=round(float(np.abs(actual - forecast).sum() / denominator * 100), 2) if denominator else None,
        mae=round(float(np.abs(actual - forecast).mean()), 3),
        bias=round(float(np.sum(forecast - actual) / denominator * 100), 2) if denominator else None,
        samples=len(actual),
        actual_sum=denominator,
        absolute_error_sum=float(np.abs(actual - forecast).sum()),
    )


def forecast(series: Series, horizon: int) -> dict:
    n = len(series.raw)
    models = ["mean", "weekday", "sba", "huber"]
    fold_scores: dict[str, list[float]] = {m: [] for m in models}
    folds = []
    # Last 28 days are untouched by model selection. Earlier two folds select the model.
    if n >= 168:
        for end in [n - 84, n - 56]:
            cleaned, _, _ = clean(series, end)
            mask = series.available[end : end + 28]
            if mask.sum() < 7:
                continue
            folds.append(
                dict(
                    train_end=series.dates[end - 1].isoformat(),
                    test_start=series.dates[end].isoformat(),
                    test_end=series.dates[end + 27].isoformat(),
                )
            )
            for model in models:
                pred = predict(
                    model,
                    series.dates[:end],
                    cleaned[:end],
                    series.available[:end],
                    series.dates[end : end + 28],
                )
                fold_scores[model].append(float(np.abs(cleaned[end : end + 28][mask] - pred[mask]).mean()))
    # Determine intermittency on the tuning prefix, excluding the outer holdout.
    prefix = series.raw[: max(1, n - 28)][series.available[: max(1, n - 28)]]
    eligible = ["mean", "sba"] if len(prefix) and np.mean(prefix == 0) > 0.6 else models
    selected = min(eligible, key=lambda m: np.mean(fold_scores[m]) if fold_scores[m] else float("inf"))
    if not folds:
        selected = "mean"
    evaluation = metric(np.array([]), np.array([]))
    baseline = evaluation.copy()
    residuals = np.array([])
    holdout = None
    if n >= 84:
        end = n - 28
        cleaned, _, _ = clean(series, end)
        pred = predict(
            selected, series.dates[:end], cleaned[:end], series.available[:end], series.dates[end:]
        )
        mask = series.available[end:]
        evaluation = metric(cleaned[end:][mask], pred[mask])
        base_pred = np.full(28, series.raw[max(0, end - 56) : end].mean())
        baseline = metric(cleaned[end:][mask], base_pred[mask])
        residuals = cleaned[end:][mask] - pred[mask]
        holdout = dict(start=series.dates[end].isoformat(), end=series.dates[-1].isoformat())
    cleaned, anomalies, threshold = clean(series, n)
    future = [series.dates[-1] + timedelta(days=i + 1) for i in range(horizon)]
    prediction = predict(selected, series.dates, cleaned, series.available, future)
    # Reconstruct only unavailable days; zeros on available days remain true zeros.
    reconstructed = predict(selected, series.dates, cleaned, series.available, series.dates)
    restored = cleaned.copy()
    restored[~series.available] = np.maximum(cleaned[~series.available], reconstructed[~series.available])
    lost = float(np.sum(restored - cleaned))
    observed = cleaned[series.available]
    sigma = (
        float(np.sqrt(np.mean(residuals**2)))
        if len(residuals)
        else (float(np.std(observed)) if len(observed) else 0.0)
    )
    if not np.isfinite(sigma):
        sigma = 0.0
    radius = float(np.quantile(np.abs(residuals), 0.9)) if len(residuals) >= 7 else 1.645 * sigma
    recent_raw = float(series.raw[-56:].mean())
    recent_clean = float(cleaned[-56:].mean())
    recent_restored = float(restored[-56:].mean())
    # Same annual phase one year apart isolates a model's learned trend for explanation.
    prior_phase = [d - timedelta(days=365) for d in future]
    prior = predict(selected, series.dates, cleaned, series.available, prior_phase)
    trend = (
        (float(prediction.mean() / prior.mean()) - 1) * 100 if selected == "huber" and prior.mean() > 0 else 0
    )
    return dict(
        model=selected,
        model_name=MODEL_NAMES[selected],
        version=MODEL_VERSION,
        daily=prediction,
        future=future,
        cleaned=cleaned,
        restored=restored,
        anomalies=anomalies,
        anomaly_threshold=threshold if np.isfinite(threshold) else None,
        lost_units=round(lost, 1),
        stockout_days=int((~series.available).sum()),
        sigma=sigma,
        radius=radius,
        evaluation=evaluation,
        baseline=baseline,
        holdout=holdout,
        folds=folds,
        candidates=[
            dict(
                model=m,
                name=MODEL_NAMES[m],
                tuning_mae=round(float(np.mean(fold_scores[m])), 3) if fold_scores[m] else None,
            )
            for m in models
        ],
        raw_daily=round(recent_raw, 2),
        cleaned_daily=round(recent_clean, 2),
        restored_daily=round(recent_restored, 2),
        trend_pct=round(trend, 1),
    )
