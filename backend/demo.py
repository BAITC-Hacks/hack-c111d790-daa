"""Deterministic 2-year synthetic data with known trend, seasonality and project sales."""

from datetime import date, timedelta

import numpy as np

from .schemas import Dataset


def make_demo() -> Dataset:
    rng = np.random.default_rng(42)
    as_of = date(2026, 9, 23)
    start = as_of - timedelta(days=730)
    definitions = [
        ("CBL-001", "Кабель ВВГнг-LS 3×2,5", "cable", "s1", "м", 420, 100, 300, 42, 0.45, 0.22, 120),
        ("CBL-002", "Кабель ВВГнг-LS 5×6", "cable", "s1", "м", 1680, 50, 100, 17, 0.5, 0.15, 650),
        ("CBL-003", "Провод ПВС 2×1,5", "cable", "s1", "м", 215, 100, 100, 29, 0.25, 0.10, 720),
        (
            "AUT-001",
            "Автоматический выключатель C16",
            "protection",
            "s2",
            "шт",
            1850,
            12,
            24,
            15,
            0.18,
            0.30,
            35,
        ),
        ("AUT-002", "УЗО 2P 40A / 30 мА", "protection", "s2", "шт", 12400, 6, 6, 5, 0.15, 0.12, 320),
        (
            "AUT-003",
            "Дифференциальный автомат C25",
            "protection",
            "s2",
            "шт",
            9800,
            6,
            12,
            8,
            0.22,
            0.18,
            110,
        ),
        ("LED-001", "Панель LED 36 Вт, 595×595", "light", "s3", "шт", 4900, 8, 16, 12, 0.52, 0.28, 70),
        ("LED-002", "Прожектор LED 100 Вт IP65", "light", "s3", "шт", 16700, 4, 8, 4, 0.6, 0.1, 140),
        ("LED-003", "Лампа LED E27 12 Вт", "light", "s3", "шт", 580, 20, 40, 24, 0.32, 0.07, 450),
        ("INS-001", "Розетка двойная с заземлением", "install", "s4", "шт", 1450, 10, 20, 19, 0.28, 0.1, 80),
        ("INS-002", "Лоток кабельный 100×50", "install", "s4", "м", 2600, 3, 12, 10, 0.5, 0.2, 450),
        ("INS-003", "Контактор 3P 95A", "install", "s4", "шт", 42500, 1, 1, 1, 0.05, 0.0, 4),
    ]
    products, inventory, sales, stockouts, inbound, materials = [], [], [], [], [], []
    for j, (sku, name, cat, supplier, unit, price, pack, moq, base, season, trend, stock) in enumerate(
        definitions
    ):
        products.append(
            dict(
                sku=sku,
                name=name,
                category_id=cat,
                supplier_id=supplier,
                unit=unit,
                purchase_price=price,
                pack_size=pack,
                moq=moq,
                growth_pct=5 if j % 3 == 0 else 0,
            )
        )
        for w, multiplier in [("Алматы", 1.0), ("Астана", 0.62)]:
            inventory.append(dict(sku=sku, warehouse=w, on_hand=round(stock * multiplier)))
            unavailable = set()
            if j % 3 == 0:
                for offset in [95, 36]:
                    a = as_of - timedelta(days=offset)
                    b = a + timedelta(days=10)
                    stockouts.append(dict(sku=sku, warehouse=w, start=a, end=b))
                    unavailable.update(a + timedelta(days=k) for k in range(11))
            for i in range(730):
                d = start + timedelta(days=i)
                if d in unavailable:
                    continue
                wave = 1 + season * np.sin(2 * np.pi * (d.timetuple().tm_yday - 90) / 365.25)
                weekday = 0.55 if d.weekday() >= 5 else 1.12
                mean = base * multiplier * wave * weekday * (1 + trend * i / 730)
                qty = (
                    int(rng.poisson(mean))
                    if j != 11
                    else (int(rng.integers(1, 5)) if rng.random() < 0.15 else 0)
                )
                if qty:
                    sales.append(
                        dict(
                            date=d,
                            sku=sku,
                            warehouse=w,
                            quantity=qty,
                            price=round(price * 1.25, 2),
                            client_id=f"anon_{rng.integers(1, 36):04d}",
                        )
                    )
            if j in [0, 3, 6]:
                # Multiple invoices to the same customer on the same day must be aggregated.
                for _ in range(3):
                    sales.append(
                        dict(
                            date=as_of - timedelta(days=18),
                            sku=sku,
                            warehouse=w,
                            quantity=base * 35,
                            price=price * 1.2,
                            client_id="anon_project001",
                        )
                    )
            if j % 2 == 0:
                inbound.append(dict(sku=sku, warehouse=w, quantity=pack * 2, eta=as_of + timedelta(days=7)))
            if j in [0, 6]:
                materials.append(
                    dict(
                        sku=sku,
                        warehouse=w,
                        quantity=pack * 2,
                        due_date=as_of + timedelta(days=12),
                        reference=f"BOM-{j}-{w}",
                    )
                )
    return Dataset(
        name="Электрокомплект · демонстрационный набор",
        synthetic=True,
        as_of=as_of,
        history_start=start,
        products=products,
        inventory=inventory,
        sales=sales,
        stockouts=stockouts,
        inbound=inbound,
        materials=materials,
        categories=[
            dict(id="cable", name="Кабель и провод", service_level=0.97, review_days=14),
            dict(id="protection", name="Модульная автоматика", service_level=0.98, review_days=14),
            dict(id="light", name="Освещение", service_level=0.95, review_days=21),
            dict(id="install", name="Электромонтаж", service_level=0.93, review_days=14),
        ],
        suppliers=[
            dict(id="s1", name="КазКабель", lead_days=18),
            dict(id="s2", name="IEK Kazakhstan", lead_days=14),
            dict(id="s3", name="Световые решения", lead_days=25),
            dict(id="s4", name="ЭлектроПрофи", lead_days=10),
        ],
    )
