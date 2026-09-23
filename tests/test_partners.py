"""Controlled tests validate logic; the actual-file benchmark is a separate, source-backed evaluation."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend import partner_store as store
from backend import storage
from backend.main import app
from backend.partner_forecast import add_month, predict, prepare, run_product
from backend.partner_import import empty_product
from backend.partner_models import ManualProduct, MonthlyInput


@pytest.fixture
def product():
    p = empty_product("TEST")
    p.update(
        company="iek",
        name="Controlled test fixture",
        unit="шт",
        snapshot_date="2026-09-22",
        monthly_sales=[dict(month=add_month("2024-01", i), quantity=300) for i in range(33)],
        stock=0,
        stock_date="2026-09-22",
        stock_scope_confirmed=True,
        moq=1,
        pack_size=1,
        lead_days=10,
        review_days=20,
        service_level=0.95,
        growth_pct=0,
    )
    return p


def test_returns_and_partial_month_are_not_positive_demand(product):
    product["monthly_sales"][0]["quantity"] = -75
    product["monthly_sales"][-1]["quantity"] = 99999999
    result = run_product(product, {"seasonality": {}})
    assert result["history"][0]["actual"] == -75
    assert result["history"][0]["regular"] == 0
    assert result["history"][-1]["month"] == "2026-08"
    assert result["holdout"] == {"start": "2026-06", "end": "2026-08"}
    assert result["forecast"][0]["quantity"] == 300
    assert result["negative_months"] == 1


def test_missing_month_is_not_an_observed_zero():
    months, raw, y, mask = prepare(
        [{"month": "2026-01", "quantity": 10}, {"month": "2026-03", "quantity": None}], "2026-04-01"
    )
    assert months == ["2026-01", "2026-02", "2026-03"]
    assert mask.tolist() == [True, False, True]
    assert y.tolist() == [10, 0, 0]


def test_no_invented_order_when_current_stock_or_scope_unknown(product):
    product["stock"] = None
    product["stock_scope_confirmed"] = False
    result = run_product(product, {"seasonality": {}})
    assert result["quantity"] is None
    assert result["forecast"]
    assert len(result["blocked"]) == 2


def test_inbound_eta_stock_materials_growth_and_pack_influence_order(product):
    baseline = run_product(product, {"seasonality": {}})
    assert baseline["quantity"] > 0 and baseline["amount"] is None
    product["inbound"] = [dict(eta="2026-09-25", quantity=100, reference="Test")]
    incoming = run_product(product, {"seasonality": {}})
    assert incoming["quantity"] == baseline["quantity"] - 100
    product["inbound"][0]["eta"] = "2027-01-01"
    assert run_product(product, {"seasonality": {}})["quantity"] == baseline["quantity"]
    product["stock"] = 100
    assert run_product(product, {"seasonality": {}})["quantity"] == baseline["quantity"] - 100
    product["materials"] = [dict(due_date="2026-09-24", quantity=200, reference="Test project")]
    assert run_product(product, {"seasonality": {}})["quantity"] == baseline["quantity"] + 100
    product.update(pack_size=12, moq=1000, purchase_price=12.5)
    r = run_product(product, {"seasonality": {}})
    assert r["quantity"] == 1008 and r["amount"] == 12600
    product.update(moq=1, pack_size=1, growth_pct=50)
    assert run_product(product, {"seasonality": {}})["forecast"][0]["quantity"] == 450


def test_explicit_stockout_recovery_and_project_exclusion(product):
    for row in product["monthly_sales"]:
        row["quantity"] = 100
    baseline = run_product(product, {"seasonality": {}})
    for row in product["monthly_sales"]:
        row["stockout_days"] = 15
    recovered = run_product(product, {"seasonality": {}})
    assert recovered["forecast"][0]["quantity"] > baseline["forecast"][0]["quantity"]
    for row in product["monthly_sales"]:
        row["stockout_days"] = 0
    product["monthly_sales"][30].update(quantity=10100, excluded_quantity=10000)
    excluded = run_product(product, {"seasonality": {}})
    assert excluded["forecast"][0]["quantity"] == baseline["forecast"][0]["quantity"]


def test_future_brand_profile_cannot_leak_into_holdout(product):
    months, _, y, mask = prepare(product["monthly_sales"], product["snapshot_date"])
    historical = {"2024": [1.0] * 12, "2025": [2.0] * 12}
    a = predict("brand", months[:29], y[:29], mask[:29], months[29:], historical)
    b = predict("brand", months[:29], y[:29], mask[:29], months[29:], historical | {"2026": [1e8] + [1] * 11})
    np.testing.assert_array_equal(a, b)


def test_holdout_does_not_select_model(product):
    before = run_product(product, {"seasonality": {}})
    for row in product["monthly_sales"][29:32]:
        row["quantity"] = 999999
    after = run_product(product, {"seasonality": {}})
    assert before["model_id"] == after["model_id"]
    assert before["tuning"] == after["tuning"]
    assert after["metrics"]["mae"] > before["metrics"]["mae"]


@pytest.mark.parametrize(
    "change",
    [{"stock": -1}, {"moq": 0}, {"lead_days": 0}, {"service_level": 1.2}, {"stock_date": "2027-01-01"}],
)
def test_manual_invalid_inputs_rejected(product, change):
    body = {k: v for k, v in product.items() if k in ManualProduct.model_fields}
    with pytest.raises(ValidationError):
        ManualProduct.model_validate(body | {"note": "Unit test"} | change)


def test_invalid_month_stockout_and_duplicate_month(product):
    with pytest.raises(ValidationError):
        MonthlyInput(month="2025-02", quantity=10, stockout_days=29)
    with pytest.raises(ValidationError):
        MonthlyInput(month="2025-02", quantity=10, excluded_quantity=11)
    body = {k: v for k, v in product.items() if k in ManualProduct.model_fields}
    with pytest.raises(ValidationError):
        ManualProduct.model_validate(
            body | {"note": "Unit test", "monthly_sales": [body["monthly_sales"][0]] * 2}
        )


def test_manual_audit_conflict_and_reproducible_runs(tmp_path, monkeypatch, product, constant_dataset):
    monkeypatch.setenv("EKT_PARTNER_DB", str(tmp_path / "partners.sqlite3"))
    monkeypatch.setenv("EKT_DB", str(tmp_path / "daily.sqlite3"))
    storage.save_dataset(constant_dataset.model_dump(mode="json"))
    with store.connect() as db:
        db.execute(
            "INSERT INTO companies VALUES(?,?)",
            ("iek", store.dumps(dict(id="iek", name="Test", seasonality={}, archive_sha256="fixture"))),
        )
        db.execute("INSERT INTO products VALUES(?,?,?)", ("iek", product["sku"], store.dumps(product)))
        db.execute("INSERT INTO raw_rows VALUES(?,?,?,?,?)", ("iek", "test.xlsx", "Sheet", 1, '["original"]'))
    with TestClient(app) as client:
        original = client.get("/api/partners/iek/product?sku=TEST").json()
        body = {k: v for k, v in product.items() if k in ManualProduct.model_fields}
        body.update(note="Confirmed test inputs", expected_version=original["version"], stock=10)
        saved = client.post("/api/partners/iek/manual", json=body)
        assert saved.status_code == 200, saved.text
        assert len(saved.json()["revisions"]) == 1
        assert client.post("/api/partners/iek/manual", json=body).status_code == 409
        run = client.post("/api/partners/iek/calculate", json={"skus": ["TEST"]}).json()
        identity = run["id"]
        assert run["rows"][0]["quantity"] > 0
        body.update(expected_version=saved.json()["version"], stock=1000)
        assert client.post("/api/partners/iek/manual", json=body).status_code == 200
        old = client.get(f"/api/partners/iek/runs/{identity}").json()
        assert old["rows"] == run["rows"]
        csv = client.get(f"/api/partners/iek/runs/{identity}/export")
        assert csv.status_code == 200 and "Черновик" in csv.text
        assert client.post("/api/partners/iek/calculate", json={"skus": ["UNKNOWN"]}).status_code == 422
    with store.connect() as db:
        assert db.execute("SELECT payload FROM raw_rows").fetchone()[0] == '["original"]'
        assert db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] == 2


def test_actual_imported_examples_read_only(monkeypatch):
    path = Path("data/partners/partners.sqlite3")
    if not path.exists():
        pytest.skip("Private partner archives are not bundled in the repository")
    # This check reads the initial import only; altered business inputs are allowed afterwards.
    monkeypatch.setenv("EKT_PARTNER_DB", str(path))
    for company, products, transactions, returns in [
        ("iek", 3184, 171585, 115),
        ("systeme", 724, 77299, 302),
    ]:
        c = store.get_company(company)
        if c is None:
            pytest.skip("Import both supplied archives first")
        assert (c["products"], c["events"]["rows"], c["events"]["returns"]) == (
            products,
            transactions,
            returns,
        )
    p = store.get_product("systeme", "300200428_")
    assert p["source_snapshot"]["Свободный остаток"] == 1118
    assert p["cost_of_sales"] == 1050.61
    if not p["manual_note"]:
        assert p["purchase_price"] is None


def test_full_stockout_month_does_not_report_negative_recovery(product):
    product["monthly_sales"][0]["stockout_days"] = 31
    result = run_product(product, {"seasonality": {}})
    assert result["restored_units"] == 0
    assert not result["history"][0]["known"]
