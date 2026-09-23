from datetime import date, timedelta

import pytest

from backend.schemas import Dataset


@pytest.fixture
def constant_dataset():
    as_of = date(2026, 9, 23)
    start = as_of - timedelta(days=365)
    return Dataset.model_validate(
        {
            "name": "Controlled fixture",
            "synthetic": True,
            "as_of": as_of,
            "history_start": start,
            "categories": [{"id": "cat", "name": "Test", "service_level": 0.95, "review_days": 14}],
            "suppliers": [{"id": "supplier", "name": "Test supplier", "lead_days": 10}],
            "products": [
                {
                    "sku": "SKU",
                    "name": "Test product",
                    "category_id": "cat",
                    "supplier_id": "supplier",
                    "purchase_price": 100,
                    "pack_size": 1,
                    "moq": 1,
                }
            ],
            "inventory": [{"sku": "SKU", "warehouse": "WH", "on_hand": 20}],
            "sales": [
                {
                    "date": start + timedelta(days=i),
                    "sku": "SKU",
                    "warehouse": "WH",
                    "quantity": 10,
                    "price": 120,
                    "client_id": "anon_001",
                }
                for i in range(365)
            ],
        }
    )
