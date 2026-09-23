from datetime import date, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from backend.forecasting import build_series, clean, forecast
from backend.planning import calculate
from backend.schemas import CalculateRequest, Dataset, Inbound, MaterialRequirement, Sale, Stockout


def row(data, **options):
    return calculate(data, CalculateRequest(**options))["rows"][0]


def test_exact_order_formula(constant_dataset):
    result = row(constant_dataset)
    assert result["demand"] == 240
    assert result["safety_stock"] == 0
    assert result["quantity"] == 220
    assert result["prearrival_shortage"] == 80
    assert result["urgency"] == "critical"
    assert "220" in result["explanation"]


def test_service_policy_increases_safety_stock(constant_dataset):
    for i, sale in enumerate(constant_dataset.sales):
        sale.quantity = 8 + (i * 17 % 13)
    low = row(constant_dataset, service_level=0.80)
    high = row(constant_dataset, service_level=0.99)
    assert high["safety_stock"] > low["safety_stock"]
    assert high["quantity"] > low["quantity"]


def test_scenario_growth_and_purchase_price(constant_dataset):
    base = row(constant_dataset)
    scenario = row(constant_dataset, growth_adjustment_pct=50)
    assert scenario["demand"] == pytest.approx(base["demand"] * 1.5)
    constant_dataset.products[0].purchase_price *= 2
    repriced = row(constant_dataset)
    assert repriced["quantity"] == base["quantity"]
    assert repriced["amount"] == base["amount"] * 2


@pytest.mark.parametrize("factor", ["sales", "stock", "inbound", "growth", "category", "lead", "materials"])
def test_every_required_source_changes_recommendation(constant_dataset, factor):
    before = row(constant_dataset)["quantity"]
    d = constant_dataset.model_copy(deep=True)
    if factor == "sales":
        for s in d.sales:
            s.quantity *= 2
    elif factor == "stock":
        d.inventory[0].on_hand += 100
    elif factor == "inbound":
        d.inbound = [Inbound(sku="SKU", warehouse="WH", quantity=100, eta=d.as_of + timedelta(days=5))]
    elif factor == "growth":
        d.products[0].growth_pct = 50
    elif factor == "category":
        d.categories[0].review_days = 30
    elif factor == "lead":
        d.suppliers[0].lead_days = 20
    elif factor == "materials":
        d.materials = [
            MaterialRequirement(sku="SKU", warehouse="WH", quantity=100, due_date=d.as_of, reference="BOM-1")
        ]
    after = row(d)["quantity"]
    assert after < before if factor in {"stock", "inbound"} else after > before


def test_stockout_restores_hidden_demand(constant_dataset):
    d = constant_dataset
    start = d.as_of - timedelta(days=42)
    d.sales = [s for s in d.sales if s.date < start]
    raw = row(d)
    d.stockouts = [Stockout(sku="SKU", warehouse="WH", start=start, end=d.as_of - timedelta(days=1))]
    corrected = row(d)
    assert corrected["quantity"] > raw["quantity"]
    assert corrected["lost_units"] == pytest.approx(420, abs=2)
    assert corrected["stockout_days"] == 42
    assert corrected["evaluation"]["samples"] == 0


def test_project_customer_split_invoices_do_not_inflate_order(constant_dataset):
    original = row(constant_dataset)
    for _ in range(5):
        constant_dataset.sales.append(
            Sale(
                date=constant_dataset.as_of - timedelta(days=8),
                sku="SKU",
                warehouse="WH",
                quantity=1000,
                price=120,
                client_id="anon_project",
            )
        )
    result = row(constant_dataset)
    assert result["quantity"] == original["quantity"]
    assert result["excluded_units"] == 5000
    assert len(result["anomalies"]) == 1


def test_recurring_large_customer_is_retained(constant_dataset):
    d = constant_dataset
    for offset in range(7, 300, 7):
        d.sales.append(
            Sale(
                date=d.as_of - timedelta(days=offset),
                sku="SKU",
                warehouse="WH",
                quantity=1000,
                price=120,
                client_id="anon_weekly",
            )
        )
    series = build_series(d.sales, [], d.history_start, d.as_of)
    cleaned, anomalies, _ = clean(series, len(series.raw))
    assert not anomalies
    assert cleaned.sum() == series.raw.sum()


def test_seasonality_and_sustained_growth_are_learned():
    start = date(2023, 1, 1)
    sales = [
        Sale(
            date=start + timedelta(days=i),
            sku="SKU",
            warehouse="WH",
            client_id="anon_001",
            quantity=round(30 + 0.025 * i + 18 * np.sin(2 * np.pi * i / 365.25), 2),
            price=100,
        )
        for i in range(900)
    ]
    series = build_series(sales, [], start, start + timedelta(days=900))
    result = forecast(series, 180)
    assert result["model"] == "huber"
    assert result["daily"].max() - result["daily"].min() > 15
    assert result["trend_pct"] > 10
    assert result["evaluation"]["wape"] < result["baseline"]["wape"]


def test_holdout_cannot_change_model_selection(constant_dataset):
    d = constant_dataset
    before = forecast(build_series(d.sales, [], d.history_start, d.as_of), 28)
    for s in d.sales[-28:]:
        s.quantity = 25
    after = forecast(build_series(d.sales, [], d.history_start, d.as_of), 28)
    assert before["model"] == after["model"]
    assert before["candidates"] == after["candidates"]
    assert before["evaluation"] != after["evaluation"]
    assert all(f["test_end"] < after["holdout"]["start"] for f in after["folds"])


def test_late_and_overdue_inbound_do_not_hide_shortage(constant_dataset):
    d = constant_dataset
    base = row(d)
    d.inbound = [
        Inbound(sku="SKU", warehouse="WH", quantity=1000, eta=d.as_of + timedelta(days=40)),
        Inbound(sku="SKU", warehouse="WH", quantity=500, eta=d.as_of - timedelta(days=1)),
    ]
    result = row(d)
    assert result["quantity"] == base["quantity"]
    assert result["late_inbound"] == 1000
    assert result["overdue_inbound"] == 500
    assert result["warnings"]
    # Even in-horizon receipts do not erase pre-arrival stockout risk.
    d.inbound = [Inbound(sku="SKU", warehouse="WH", quantity=1000, eta=d.as_of + timedelta(days=20))]
    result = row(d)
    assert result["quantity"] == 0
    assert result["urgency"] == "critical"


def test_rounding_moq_and_no_unnecessary_order(constant_dataset):
    d = constant_dataset
    d.products[0].pack_size = 24
    d.products[0].moq = 250
    assert row(d)["quantity"] == 264
    d.inventory[0].on_hand = 10000
    assert row(d)["quantity"] == 0


def test_warehouse_isolation_and_supplier_groups(constant_dataset):
    payload = constant_dataset.model_dump(mode="json")
    payload["inventory"].append({"sku": "SKU", "warehouse": "OTHER", "on_hand": 99999})
    data = Dataset.model_validate(payload)
    result = calculate(data, CalculateRequest())
    assert len(result["rows"]) == 2
    assert len(result["suppliers"]) == 1
    assert result["suppliers"][0]["positions"] == 1
    assert row(data, warehouse="WH")["quantity"] == 220


@pytest.mark.parametrize(
    "mutation", ["negative", "pii", "extra", "unknown_sku", "duplicate_inventory", "future", "nan"]
)
def test_invalid_inputs_are_rejected(constant_dataset, mutation):
    payload = constant_dataset.model_dump(mode="json")
    if mutation == "negative":
        payload["inventory"][0]["on_hand"] = -1
    if mutation == "pii":
        payload["sales"][0]["client_id"] = "real.person@example.com"
    if mutation == "extra":
        payload["sales"][0]["client_name"] = "Name"
    if mutation == "unknown_sku":
        payload["sales"][0]["sku"] = "MISSING"
    if mutation == "duplicate_inventory":
        payload["inventory"].append(payload["inventory"][0])
    if mutation == "future":
        payload["sales"][0]["date"] = payload["as_of"]
    if mutation == "nan":
        payload["products"][0]["purchase_price"] = float("nan")
    with pytest.raises(ValidationError):
        Dataset.model_validate(payload)


def test_no_sales_does_not_crash_and_all_stockout_warns(constant_dataset):
    d = constant_dataset
    d.sales = []
    assert row(d)["quantity"] == 0
    d.stockouts = [
        Stockout(sku="SKU", warehouse="WH", start=d.history_start, end=d.as_of - timedelta(days=1))
    ]
    result = row(d)
    assert result["confidence"] == "limited"
    assert result["warnings"]
