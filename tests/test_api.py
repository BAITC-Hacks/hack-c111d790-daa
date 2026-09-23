import csv
import io

import pytest
from fastapi.testclient import TestClient

from backend import storage
from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch, constant_dataset):
    monkeypatch.setenv("EKT_DB", str(tmp_path / "test.sqlite3"))
    storage.save_dataset(constant_dataset.model_dump(mode="json"))
    with TestClient(app) as c:
        yield c


def test_end_to_end_approval_export_and_persistence(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/dataset").json()["synthetic"]
    response = client.post("/api/runs", json={"warehouse": "WH"})
    assert response.status_code == 200
    run = response.json()
    identity = run["id"]
    assert run["status"] == "draft"
    assert client.get(f"/api/runs/{identity}/export").text.startswith("\ufeffСтатус;")
    request = {
        "lines": [{"sku": "SKU", "warehouse": "WH", "quantity": 250}],
        "note": "Проверено ответственным сотрудником",
        "confirmed": False,
    }
    assert client.post(f"/api/runs/{identity}/approve", json=request).status_code == 422
    request["confirmed"] = True
    response = client.post(f"/api/runs/{identity}/approve", json=request)
    assert response.status_code == 200
    assert response.json()["approval"]["amount"] == 25000
    assert client.post(f"/api/runs/{identity}/approve", json=request).status_code == 409
    saved = client.get(f"/api/runs/{identity}").json()
    assert saved["status"] == "approved"
    export = client.get(f"/api/runs/{identity}/export")
    rows = list(csv.DictReader(io.StringIO(export.text.lstrip("\ufeff")), delimiter=";"))
    assert rows[0]["Количество"] == "250"
    assert rows[0]["Статус"] == "Утверждён"
    with storage.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM audit WHERE action='run_approved'").fetchone()[0] == 1
    assert client.get("/api/runs").json()[0]["id"] == identity


def test_unknown_missing_duplicate_lines_and_invalid_pack(client, constant_dataset):
    constant_dataset.products[0].pack_size = 12
    assert client.post("/api/dataset", json=constant_dataset.model_dump(mode="json")).status_code == 200
    identity = client.post("/api/runs", json={}).json()["id"]
    request = {
        "confirmed": True,
        "note": "Reviewed",
        "lines": [{"sku": "SKU", "warehouse": "WH", "quantity": 25}],
    }
    assert client.post(f"/api/runs/{identity}/approve", json=request).status_code == 422
    request["lines"][0]["quantity"] = 24
    request["lines"].append(request["lines"][0])
    assert client.post(f"/api/runs/{identity}/approve", json=request).status_code == 422
    assert client.post("/api/runs", json={"warehouse": "MISSING"}).status_code == 422
    assert client.get("/api/runs/missing").status_code == 404


def test_import_validation_and_csv_formula_escaping(client, constant_dataset):
    payload = constant_dataset.model_dump(mode="json")
    payload["products"][0]["name"] = '=HYPERLINK("https://example.com")'
    assert client.post("/api/dataset", json=payload).status_code == 200
    identity = client.post("/api/runs", json={}).json()["id"]
    export = client.get(f"/api/runs/{identity}/export").text
    rows = list(csv.reader(io.StringIO(export.lstrip("\ufeff")), delimiter=";"))
    assert rows[1][2].startswith("'=HYPERLINK")
    payload["sales"][0]["client_id"] = "John Smith"
    assert client.post("/api/dataset", json=payload).status_code == 422
    assert client.get("/api/dataset/schema").json()["title"] == "Dataset"
    assert client.get("/api/dataset/download").status_code == 200
