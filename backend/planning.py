"""Deterministic order-up-to policy and traceable time-phased stock projection."""

from collections import defaultdict
from datetime import timedelta
from math import ceil, sqrt
from statistics import NormalDist

import numpy as np

from .forecasting import MODEL_VERSION, build_series, forecast
from .schemas import CalculateRequest, Dataset


def calculate(dataset: Dataset, options: CalculateRequest) -> dict:
    categories = {c.id: c for c in dataset.categories}
    products = {p.sku: p for p in dataset.products}
    suppliers = {s.id: s for s in dataset.suppliers}
    indexed = {}
    for source in ["sales", "stockouts", "inbound", "materials"]:
        groups = defaultdict(list)
        for item in getattr(dataset, source):
            groups[item.sku, item.warehouse].append(item)
        indexed[source] = groups
    rows = []
    for inv in dataset.inventory:
        product = products[inv.sku]
        if options.warehouse and inv.warehouse != options.warehouse:
            continue
        if options.category_id and product.category_id != options.category_id:
            continue
        key = inv.sku, inv.warehouse
        category = categories[product.category_id]
        supplier = suppliers[product.supplier_id]
        review = options.review_days if options.review_days is not None else category.review_days
        service = options.service_level if options.service_level is not None else category.service_level
        horizon = supplier.lead_days + review
        series = build_series(
            indexed["sales"][key], indexed["stockouts"][key], dataset.history_start, dataset.as_of
        )
        f = forecast(series, horizon)
        growth = (1 + product.growth_pct / 100) * (1 + options.growth_adjustment_pct / 100)
        daily = f["daily"] * growth
        demand = float(daily.sum())
        # Approximation: independent daily errors, normal lead-time aggregation.
        safety = ceil(NormalDist().inv_cdf(service) * f["sigma"] * growth * sqrt(horizon))
        last = dataset.as_of + timedelta(days=horizon - 1)
        incoming = [i for i in indexed["inbound"][key] if dataset.as_of <= i.eta <= last]
        overdue = [i for i in indexed["inbound"][key] if i.eta < dataset.as_of]
        late = [i for i in indexed["inbound"][key] if i.eta > last]
        requirements = [m for m in indexed["materials"][key] if m.due_date <= last]
        inbound_qty = sum(i.quantity for i in incoming)
        material_qty = sum(m.quantity for m in requirements)
        net = max(0, demand + safety + material_qty - inv.on_hand - inbound_qty)
        quantity = ceil(max(net, product.moq) / product.pack_size) * product.pack_size if net > 0 else 0
        projection, stock = [], float(inv.on_hand)
        first_shortage = None
        prearrival_shortage = 0.0
        for offset, (d, qty) in enumerate(zip(f["future"], daily)):
            stock += sum(i.quantity for i in incoming if i.eta == d)
            stock -= qty + sum(m.quantity for m in requirements if max(m.due_date, dataset.as_of) == d)
            if stock < 0 and first_shortage is None:
                first_shortage = offset
            if offset < supplier.lead_days:
                prearrival_shortage = max(prearrival_shortage, -stock)
            projection.append(dict(date=d.isoformat(), stock=round(stock, 1)))
        urgency = "critical" if prearrival_shortage > 0 else "plan" if quantity else "healthy"
        warnings = []
        available_days = int(series.available.sum())
        if available_days < 56:
            warnings.append(
                "Мало дней наличия: прогноз требует ручной проверки; нулевой прогноз не означает отсутствие спроса."
            )
        if len(series.dates) < 400:
            warnings.append(
                "Недостаточно истории для годовой сезонности: используется короткий профиль спроса."
            )
        if overdue:
            warnings.append(
                f"Просрочено поступление {sum(i.quantity for i in overdue):g} {product.unit}; исключено до уточнения ETA."
            )
        if prearrival_shortage > 0:
            warnings.append(
                f"До новой поставки ожидается нехватка {ceil(prearrival_shortage)} {product.unit}. Нужны ускорение или перемещение."
            )
        if f["evaluation"]["wape"] is not None and f["evaluation"]["wape"] > 40:
            warnings.append("Высокая ошибка на holdout: проверьте проектные продажи и параметры поставки.")
        excluded = sum(a["quantity"] for a in f["anomalies"])
        explanation = (
            f"Спрос за {horizon} дн. {demand:.0f} + страховой запас {safety} + ведомость {material_qty:g} "
            f"− остаток {inv.on_hand:g} − в пути {inbound_qty:g} = {net:.0f} {product.unit}. "
            f"С учётом партии {product.pack_size} и MOQ {product.moq}: {quantity} {product.unit}."
        )
        history = [
            dict(
                date=d.isoformat(),
                actual=round(float(series.raw[i]), 2),
                regular=round(float(f["cleaned"][i]), 2),
                restored=round(float(f["restored"][i]), 2),
                stockout=not bool(series.available[i]),
            )
            for i, d in enumerate(series.dates)
        ]
        prediction = [
            dict(
                date=d.isoformat(),
                forecast=round(float(q), 2),
                lower=round(max(0, float(q) - f["radius"] * growth), 2),
                upper=round(float(q) + f["radius"] * growth, 2),
            )
            for d, q in zip(f["future"], daily)
        ]
        rows.append(
            dict(
                sku=product.sku,
                name=product.name,
                warehouse=inv.warehouse,
                category_id=category.id,
                category=category.name,
                supplier_id=supplier.id,
                supplier=supplier.name,
                unit=product.unit,
                price=product.purchase_price,
                quantity=quantity,
                amount=round(quantity * product.purchase_price, 2),
                on_hand=inv.on_hand,
                inbound=inbound_qty,
                late_inbound=sum(i.quantity for i in late),
                overdue_inbound=sum(i.quantity for i in overdue),
                material_demand=material_qty,
                demand=round(demand, 2),
                safety_stock=safety,
                net_need=round(net, 2),
                lead_days=supplier.lead_days,
                review_days=review,
                horizon=horizon,
                service_level=service,
                pack_size=product.pack_size,
                moq=product.moq,
                growth_pct=round((growth - 1) * 100, 2),
                days_to_shortage=first_shortage,
                prearrival_shortage=ceil(prearrival_shortage),
                urgency=urgency,
                explanation=explanation,
                warnings=warnings,
                excluded_units=excluded,
                lost_units=f["lost_units"],
                stockout_days=f["stockout_days"],
                anomalies=f["anomalies"],
                model=f["model"],
                model_name=f["model_name"],
                trend_pct=f["trend_pct"],
                raw_daily=f["raw_daily"],
                cleaned_daily=f["cleaned_daily"],
                restored_daily=f["restored_daily"],
                forecast_daily=round(float(daily.mean()), 2),
                evaluation=f["evaluation"],
                baseline=f["baseline"],
                folds=f["folds"],
                holdout=f["holdout"],
                candidates=f["candidates"],
                history=history,
                forecast=prediction,
                projection=projection,
                confidence="limited"
                if available_days < 56 or f["evaluation"]["samples"] < 14
                else "evaluated",
            )
        )
    rows.sort(key=lambda r: ({"critical": 0, "plan": 1, "healthy": 2}[r["urgency"]], -r["amount"]))
    supplier_groups = []
    for supplier in dataset.suppliers:
        grouped = [r for r in rows if r["supplier_id"] == supplier.id and r["quantity"] > 0]
        if grouped:
            supplier_groups.append(
                dict(
                    id=supplier.id,
                    name=supplier.name,
                    lead_days=supplier.lead_days,
                    positions=len(grouped),
                    amount=round(sum(r["amount"] for r in grouped), 2),
                )
            )
    valid = [r for r in rows if r["evaluation"]["wape"] is not None]
    value_denominator = sum(r["evaluation"]["actual_sum"] * r["price"] for r in rows)
    value_metrics = {
        key: round(
            sum(r[field]["absolute_error_sum"] * r["price"] for r in rows) / value_denominator * 100, 1
        )
        if value_denominator
        else None
        for key, field in [("value_wape", "evaluation"), ("baseline_value_wape", "baseline")]
    }
    return dict(
        as_of=dataset.as_of.isoformat(),
        synthetic=dataset.synthetic,
        dataset_name=dataset.name,
        model_version=MODEL_VERSION,
        options=options.model_dump(),
        rows=rows,
        suppliers=supplier_groups,
        summary=dict(
            **value_metrics,
            positions=len(rows),
            to_order=sum(r["quantity"] > 0 for r in rows),
            critical=sum(r["urgency"] == "critical" for r in rows),
            total_amount=round(sum(r["amount"] for r in rows), 2),
            anomaly_events=sum(len(r["anomalies"]) for r in rows),
            excluded_by_unit={
                unit: sum(r["excluded_units"] for r in rows if r["unit"] == unit)
                for unit in sorted({r["unit"] for r in rows})
            },
            lost_by_unit={
                unit: round(sum(r["lost_units"] for r in rows if r["unit"] == unit), 1)
                for unit in sorted({r["unit"] for r in rows})
            },
            mean_wape=round(float(np.mean([r["evaluation"]["wape"] for r in valid])), 1) if valid else None,
            baseline_mean_wape=round(float(np.mean([r["baseline"]["wape"] for r in valid])), 1)
            if valid
            else None,
        ),
    )
