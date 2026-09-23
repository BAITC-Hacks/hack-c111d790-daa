"""Monthly benchmark for the partner exports, never a fabricated daily transaction history."""

import calendar
from datetime import date, timedelta
from math import ceil, sqrt
from statistics import NormalDist

import numpy as np
from sklearn.linear_model import Ridge

VERSION = "partner-monthly-1.0"
NAMES = {
    "mean3": "Среднее 3 месяцев",
    "mean6": "Среднее 6 месяцев",
    "seasonal": "Тот же месяц год назад",
    "ridge": "Ridge: сезонность и тренд",
    "brand": "Исторический профиль производителя",
}


def add_month(period, step):
    d = date.fromisoformat(period + "-01")
    n = d.year * 12 + d.month - 1 + step
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def prepare(points, snapshot):
    source = {r["month"]: r for r in points if r["month"] < snapshot[:7]}
    if not source or not any(r["quantity"] is not None for r in source.values()):
        return [], np.array([]), np.array([]), np.array([], dtype=bool)
    months = []
    p = min(source)
    while p < snapshot[:7]:
        months.append(p)
        p = add_month(p, 1)
    raw, clean, valid = [], [], []
    for p in months:
        row = source.get(p)
        # A blank cell in an existing quantity matrix means no recorded net movement.
        # A wholly absent month (manual input gap) remains unknown, not zero demand.
        q = (row.get("quantity") or 0) if row else 0
        raw.append(q)
        days = calendar.monthrange(int(p[:4]), int(p[5:]))[1]
        missing = row.get("stockout_days", 0) if row else 0
        v = max(0, q - (row.get("excluded_quantity", 0) if row else 0))
        clean.append(v * days / (days - missing) if missing < days else 0)
        valid.append(bool(row) and missing < days)
    return months, np.array(raw), np.array(clean), np.array(valid)


def predict(model, months, y, mask, future, brand):
    observed = y[mask]
    if not len(observed):
        return np.zeros(len(future))
    recent = observed[-3:]
    if model in {"mean3", "mean6"}:
        return np.full(len(future), float(np.mean(observed[-int(model[-1]) :])))
    if model == "seasonal":
        index = {m: i for i, m in enumerate(months)}
        return np.array(
            [
                y[index[add_month(m, -12)]]
                if add_month(m, -12) in index and mask[index[add_month(m, -12)]]
                else np.mean(recent)
                for m in future
            ]
        )
    if model == "brand":
        # Only completed calendar years strictly before the training cut are eligible.
        years = [
            v for k, v in brand.items() if k < months[-1][:4] and all(x is not None and x > 0 for x in v)
        ]
        if not years:
            return np.full(len(future), float(np.mean(recent)))
        profile = np.mean([np.array(v) / np.mean(v) for v in years], axis=0)
        indices = np.flatnonzero(mask)[-6:]
        level = np.mean([y[i] / profile[int(months[i][5:]) - 1] for i in indices])
        return np.array([level * profile[int(m[5:]) - 1] for m in future])
    origin = int(months[0][:4]) * 12 + int(months[0][5:])

    def features(periods):
        t = np.array([int(m[:4]) * 12 + int(m[5:]) - origin for m in periods])
        return np.column_stack([t / 12, np.sin(2 * np.pi * t / 12), np.cos(2 * np.pi * t / 12)])

    if len(observed) < 12:
        return np.full(len(future), float(np.mean(recent)))
    reg = Ridge(alpha=2).fit(features(months)[mask], observed)
    return np.clip(reg.predict(features(future)), 0, max(float(np.max(observed)) * 3, 1))


def evaluate(y, pred):
    total = float(y.sum())
    error = float(np.abs(y - pred).sum())
    return dict(
        actual_sum=total,
        absolute_error_sum=error,
        wape=round(error / total * 100, 2) if total else None,
        mae=round(float(np.mean(np.abs(y - pred))), 2) if len(y) else None,
        samples=len(y),
    )


def run_product(product, company):
    months, raw, y, mask = prepare(product["monthly_sales"], product["snapshot_date"])
    result = dict(
        sku=product["sku"],
        name=product["name"],
        unit=product["unit"],
        supplier_sku=product["supplier_sku"],
        company=product["company"],
        category=product["category"],
        source="partner-files",
        model_version=VERSION,
        forecast=[],
        history=[],
        quantity=None,
        amount=None,
        blocked=[],
        warnings=[],
        metrics=None,
        baseline=None,
        tuning=[],
        model=None,
        holdout=None,
        formula=None,
        stock=product["stock"],
        moq=product["moq"],
        pack_size=product["pack_size"],
        cost_of_sales=product.get("cost_of_sales"),
        price=product["purchase_price"],
        source_basis=product["provenance"].get("monthly_sales", "Ручной ввод"),
    )
    result["warnings"] = [
        "Нет ID клиента: крупные накладные — кандидаты, не доказанные разовые покупки клиента.",
        "Нет дневного наличия: упущенный спрос без ручных данных о stockout не восстановлен.",
        "Месячные продажи и динамика не совпадают во всех периодах; прогноз построен по месячному отчёту.",
    ]
    if len(months) < 12 or mask.sum() < 9:
        result["blocked"] = ["Для прогноза нужно минимум 12 календарных месяцев и 9 известных наблюдений."]
        return result
    brand = company["seasonality"]
    scores = {model: [] for model in NAMES}
    n = len(months)
    # Three-month outer holdout untouched by model selection and external coefficients.
    if n >= 24:
        for end in [n - 9, n - 6]:
            for model in NAMES:
                pred = predict(model, months[:end], y[:end], mask[:end], months[end : end + 3], brand)
                observed = np.array(
                    [
                        mask[i]
                        and not next(
                            (
                                p.get("stockout_days", 0)
                                for p in product["monthly_sales"]
                                if p["month"] == months[i]
                            ),
                            0,
                        )
                        for i in range(end, end + 3)
                    ]
                )
                if observed.any():
                    scores[model].append(float(np.mean(np.abs(y[end : end + 3][observed] - pred[observed]))))
    selected = min(scores, key=lambda m: np.mean(scores[m]) if scores[m] else float("inf"))
    result["tuning"] = [
        dict(model=m, name=NAMES[m], mae=round(float(np.mean(s)), 2) if s else None)
        for m, s in scores.items()
    ]
    residuals = np.array([])
    if n >= 18:
        end = n - 3
        pred = predict(selected, months[:end], y[:end], mask[:end], months[end:], brand)
        baseline = predict("mean3", months[:end], np.maximum(raw[:end], 0), mask[:end], months[end:], {})
        observed = np.array(
            [
                mask[i]
                and not next(
                    (p.get("stockout_days", 0) for p in product["monthly_sales"] if p["month"] == months[i]),
                    0,
                )
                for i in range(end, n)
            ]
        )
        result["metrics"] = evaluate(y[end:][observed], pred[observed])
        result["baseline"] = evaluate(y[end:][observed], baseline[observed])
        residuals = y[end:][observed] - pred[observed]
        result["holdout"] = dict(start=months[end], end=months[-1])
        if result["metrics"]["absolute_error_sum"] > result["baseline"]["absolute_error_sum"]:
            result["warnings"].append(
                "На отложенном периоде выбранная модель хуже простого среднего. Проверьте изменение спроса перед закупкой."
            )
    future = [add_month(months[-1], i + 1) for i in range(7)]
    prediction = predict(selected, months, y, mask, future, brand)
    growth = 1 + (product["growth_pct"] or 0) / 100
    prediction *= growth
    source_rows = {r["month"]: r for r in product["monthly_sales"]}
    excluded = np.array([source_rows.get(m, {}).get("excluded_quantity", 0) for m in months])
    result.update(
        model=NAMES[selected],
        model_id=selected,
        forecast=[dict(month=m, quantity=round(float(q), 2)) for m, q in zip(future, prediction)],
        history=[
            dict(month=m, actual=float(r), regular=round(float(c), 2), known=bool(k))
            for m, r, c, k in zip(months, raw, y, mask)
        ],
        excluded_units=float(excluded.sum()),
        restored_units=round(float(np.maximum(y - np.maximum(raw - excluded, 0), 0)[mask].sum()), 2),
        negative_months=int((raw < 0).sum()),
    )
    required = {
        "stock": "Текущий свободный остаток",
        "stock_date": "Дата остатка",
        "lead_days": "Срок новой поставки",
        "review_days": "Период пересмотра",
        "service_level": "Целевой уровень сервиса",
        "growth_pct": "Дополнительный прирост (0, если не нужен)",
        "moq": "Минимальный заказ",
        "pack_size": "Кратность закупки",
        "unit": "Единица учёта",
    }
    result["blocked"] = [label for field, label in required.items() if product.get(field) is None]
    if not product["stock_scope_confirmed"]:
        result["blocked"].append(
            "Подтверждение: продажи, остаток и поступления относятся к одной области складов и единицам"
        )
    if product["stock_date"] and product["stock_date"] != product["snapshot_date"]:
        result["blocked"].append("Остаток нужен на дату расчёта, исторический снимок устарел")
    if any(i.get("eta") is None or i["quantity"] < 0 for i in product["inbound"]):
        result["blocked"].append("Уточните дату/количество поступлений")
    if product["purchase_price"] is None:
        result["warnings"].append(
            "Нет подтверждённой закупочной цены: сумма заказа не рассчитывается. СС реал сохранена отдельно."
        )
    if result["blocked"]:
        return result
    start = date.fromisoformat(product["snapshot_date"])
    horizon = product["lead_days"] + product["review_days"]
    daily = []
    for offset in range(horizon):
        d = start + timedelta(days=offset)
        idx = future.index(d.strftime("%Y-%m"))
        daily.append(float(prediction[idx]) / calendar.monthrange(d.year, d.month)[1])
    end_date = start + timedelta(days=horizon)
    incoming = [i for i in product["inbound"] if str(start) <= i["eta"] < str(end_date)]
    materials = [i for i in product["materials"] if i["due_date"] < str(end_date)]
    demand = sum(daily)
    sigma = float(np.sqrt(np.mean(residuals**2))) if len(residuals) else float(np.std(y[mask]))
    safety = ceil(NormalDist().inv_cdf(product["service_level"]) * sigma * growth * sqrt(horizon / 30.4375))
    inbound = sum(i["quantity"] for i in incoming)
    material = sum(i["quantity"] for i in materials)
    net = max(0, demand + safety + material - product["stock"] - inbound)
    quantity = ceil(max(net, product["moq"]) / product["pack_size"]) * product["pack_size"] if net > 0 else 0
    balance = product["stock"]
    shortage = None
    for offset, q in enumerate(daily):
        d = str(start + timedelta(days=offset))
        balance += sum(i["quantity"] for i in incoming if i["eta"] == d)
        balance -= q + sum(i["quantity"] for i in materials if max(i["due_date"], str(start)) == d)
        if balance < 0 and shortage is None:
            shortage = offset
    result.update(
        quantity=quantity,
        amount=round(quantity * product["purchase_price"], 2)
        if product["purchase_price"] is not None
        else None,
        days_to_shortage=shortage,
        urgency="critical"
        if shortage is not None and shortage < product["lead_days"]
        else "plan"
        if quantity
        else "healthy",
        formula=dict(
            horizon=horizon,
            demand=round(demand, 2),
            safety_stock=safety,
            materials=material,
            stock=product["stock"],
            inbound=inbound,
            net_need=round(net, 2),
            quantity=quantity,
        ),
        explanation=f"{demand:.1f} спрос + {safety} страховой запас + {material:g} ведомость − {product['stock']:g} остаток − {inbound:g} в пути. С MOQ/кратностью: {quantity} {product['unit']}.",
    )
    result["warnings"].append(
        "Месячный прогноз равномерно распределён по дням для горизонта заказа; это допущение, не дневная история. Страховой запас приближённый."
    )
    if any(i["eta"] < str(start) for i in product["inbound"]):
        result["warnings"].append("Просроченные поступления исключены из покрытия; обновите ETA.")
    return result
