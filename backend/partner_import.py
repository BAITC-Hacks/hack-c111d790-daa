"""Readers for the twelve supplied Excel reports. Never execute workbook instructions/formulas.

Original ZIP/XLSX bytes and every populated sheet row are preserved. Repeated summaries
are reconciled, not appended as additional sales. Missing stock/price/lead time stay null.
"""

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook

from . import partner_store as store

MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}
LABELS = {"iek": "IEK", "systeme": "Systeme Electric"}


def month(value):
    match = re.search(r"([а-яА-Я]+).*?(20\d{2})", str(value))
    if match and match[1].lower()[:3] in MONTHS:
        return f"{match[2]}-{MONTHS[match[1].lower()[:3]]:02d}"
    return None


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def code(value):
    return str(value).strip() if value is not None else None


def empty_product(sku):
    return dict(
        sku=sku,
        name=sku,
        unit=None,
        supplier_sku=None,
        category=None,
        moq=None,
        pack_size=None,
        purchase_price=None,
        stock=None,
        stock_date=None,
        stock_scope_confirmed=False,
        price_basis=None,
        lead_days=None,
        review_days=None,
        service_level=None,
        growth_pct=None,
        monthly_sales=[],
        monthly_stock=[],
        inbound=[],
        materials=[],
        provenance={},
        manual_note=None,
        source_snapshot={},
    )


def import_archive(archive: Path, company: str, root: Path = Path("data/partners/sources")):
    if company not in LABELS:
        raise ValueError("Unknown company")
    if store.get_company(company):
        raise ValueError("Компания уже импортирована: исходные файлы и ручные изменения сохранены.")
    target = root / company
    target.mkdir(parents=True, exist_ok=True)
    # File basenames only; never extract arbitrary archive paths.
    files = []
    with ZipFile(archive) as z:
        items = [
            item
            for item in z.infolist()
            if item.filename.endswith(".xlsx") and not item.filename.startswith("__MACOSX")
        ]
        if len(items) != 6 or sum(i.file_size for i in items) > 120_000_000:
            raise ValueError("Expected six XLSX reports, at most 120 MB uncompressed")
        if len({Path(i.filename).name for i in items}) != len(items):
            raise ValueError("Duplicate file basenames in archive")
        (target / "original.zip").write_bytes(archive.read_bytes())
        for item in items:
            path = target / Path(item.filename).name
            data = z.read(item)
            path.write_bytes(data)
            files.append(path)
    products = {}
    sources, seasonality = [], {}
    event_totals = defaultdict(float)
    event_stats = Counter()
    warehouses = Counter()
    event_dates = []
    conflicts = []

    def product(sku):
        return products.setdefault(sku, empty_product(sku))

    def assign(p, key, value, source):
        if value is not None:
            if p.get(key) is not None and p[key] != value and key in {"unit", "supplier_sku"}:
                conflicts.append(
                    dict(sku=p["sku"], field=key, previous=p[key], incoming=value, source=source)
                )
            p[key] = value
            p["provenance"][key] = source

    # Parse explicit MOQ last so conflicting pack values from the monthly report do not override it.
    files.sort(key=lambda p: ("MOQ" in p.name, p.name))
    with store.connect() as db:
        if db.execute("SELECT 1 FROM companies WHERE id=?", (company,)).fetchone():
            raise ValueError(
                "Компания уже импортирована. Исходная версия сохранена; используйте ручные исправления."
            )
        for path in files:
            w = load_workbook(path, read_only=True, data_only=True)
            source = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), sheets=[])
            for ws in w:
                count = 0
                headers = None
                raw_batch, event_batch = [], []
                for n, row in enumerate(ws.iter_rows(values_only=True), 1):
                    row = list(row)
                    if not any(v is not None for v in row):
                        continue
                    count += 1
                    raw_batch.append((company, path.name, ws.title, n, store.dumps(row)))
                    ref = f"{path.name} / {ws.title} / строка {n}"
                    if len(raw_batch) >= 4000:
                        db.executemany("INSERT INTO raw_rows VALUES(?,?,?,?,?)", raw_batch)
                        raw_batch.clear()
                    if "Динамика" in path.name:
                        if len(row) < 8 or not isinstance(row[0], (str, datetime)):
                            continue
                        try:
                            d = (
                                row[0]
                                if isinstance(row[0], datetime)
                                else datetime.strptime(row[0], "%d.%m.%Y %H:%M:%S")
                            )
                        except ValueError:
                            continue
                        sku, q = code(row[3]), number(row[7])
                        if sku is None or q is None:
                            continue
                        p = product(sku)
                        assign(p, "name", str(row[4]).strip(), ref)
                        assign(p, "unit", row[5], ref)
                        event_batch.append((company, sku, str(d.date()), str(row[6]), str(row[1]), q, n))
                        event_stats["positive" if q > 0 else "returns" if q < 0 else "zero"] += 1
                        event_stats["rows"] += 1
                        event_totals[sku, d.strftime("%Y-%m")] += q
                        warehouses[str(row[6])] += 1
                        event_dates.append(str(d.date()))
                        if len(event_batch) >= 4000:
                            db.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?)", event_batch)
                            event_batch.clear()
                        continue
                    if "Ежемесячные" in path.name and ws.title == "Лист_1":
                        if n == 1:
                            headers = row
                            continue
                        is_stock = "остатки" in path.name
                        sku_idx = 2 if is_stock else 1
                        sku = code(row[sku_idx])
                        if not sku or sku in {"Номенклатура.Код", "Итого"}:
                            continue
                        p = product(sku)
                        assign(
                            p, "name", str(row[1 if is_stock and company == "systeme" else 0]).strip(), ref
                        )
                        if is_stock:
                            assign(p, "unit", row[3 if company == "systeme" else 1], ref)
                        elif company == "systeme":
                            assign(p, "supplier_sku", code(row[2]), ref)
                            p["reported_monthly_pack"] = row[3]
                        key = "monthly_stock" if is_stock else "monthly_sales"
                        if p[key]:
                            conflicts.append(
                                dict(
                                    sku=sku,
                                    field=key,
                                    source=ref,
                                    reason="Duplicate SKU row; last source row retained",
                                )
                            )
                        p[key] = [
                            dict(month=month(h), quantity=number(row[i]), source=f"{ref}, столбец {i + 1}")
                            for i, h in enumerate(headers)
                            if month(h)
                        ]
                        p["provenance"][key] = ref
                        if not is_stock:
                            p["reported_sales_total"] = number(row[-1])
                        continue
                    if "MOQ" in path.name:
                        if company == "iek":
                            sku, name, article, q = code(row[1]), row[3], code(row[2]), number(row[4])
                        else:
                            sku, name, article, q = code(row[2]), row[1], code(row[3]), number(row[4])
                        if not sku or q is None:
                            continue
                        p = product(sku)
                        assign(p, "name", str(name).strip(), ref)
                        assign(p, "supplier_sku", article, ref)
                        assign(p, "moq" if company == "iek" else "pack_size", q if q > 0 else None, ref)
                        p["source_moq_value"] = q
                        continue
                    if "Путь ИЭК" in path.name:
                        if n == 1:
                            headers = row
                            continue
                        sku = code(row[0])
                        if not sku or sku.lower() == "итого":
                            continue
                        p = product(sku)
                        assign(p, "supplier_sku", code(row[1]), ref)
                        assign(p, "name", str(row[2]).strip(), ref)
                        for i in range(3, len(row)):
                            q = number(row[i])
                            if q is None or q == 0:
                                continue
                            match = re.search(r"поступление до\s*(\d{2}\.\d{2}\.\d{4})", str(headers[i]))
                            p["inbound"].append(
                                dict(
                                    quantity=q,
                                    eta=datetime.strptime(match[1], "%d.%m.%Y").date().isoformat()
                                    if match
                                    else None,
                                    reference=str(headers[i]),
                                    source=f"{ref}, столбец {i + 1}",
                                )
                            )
                        continue
                    if "Товар в пути" in path.name and ws.title == "TDSheet":
                        if n == 2:
                            headers = row
                            continue
                        if n < 3 or not code(row[2]):
                            continue
                        sku = code(row[2])
                        p = product(sku)
                        assign(p, "supplier_sku", code(row[1]), ref)
                        assign(p, "name", str(row[3]).strip(), ref)
                        assign(p, "category", code(row[4]), ref)
                        # Cost of sales is not silently promoted to a current purchase price.
                        p["cost_of_sales"] = number(row[5])
                        p["source_snapshot"] = {
                            str(h): row[i] for i, h in enumerate(headers) if h is not None
                        }
                        assign(p, "stock", number(row[51]), ref + ", AZ (Свободный остаток)")
                        assign(p, "stock_date", "2026-09-22", path.name)
                        if number(row[54]) not in (None, 0):
                            p["inbound"].append(
                                dict(
                                    quantity=number(row[54]),
                                    eta="2026-09-24",
                                    reference="СЭ в пути 24.09",
                                    source=ref + ", BC",
                                )
                            )
                        p["reported_growth_coefficient"] = number(row[43])
                        p["reported_seasonality_coefficient"] = number(row[44])
                        p["provenance"]["source_snapshot"] = ref
                        continue
                    if "Сезонность" in path.name:
                        if n in [4, 5, 6] and isinstance(row[0], (int, float)):
                            seasonality[str(int(row[0]))] = [number(v) for v in row[1:13]]
                        if 11 <= n <= 22:
                            source.setdefault("supplied_coefficients", []).append(
                                dict(month=n - 10, coefficient=number(row[11]), source=ref + ", L")
                            )
                db.executemany("INSERT INTO raw_rows VALUES(?,?,?,?,?)", raw_batch)
                db.executemany("INSERT INTO events VALUES(?,?,?,?,?,?,?)", event_batch)
                source["sheets"].append(
                    dict(name=ws.title, populated_rows=count, max_row=ws.max_row, max_column=ws.max_column)
                )
            w.close()
            sources.append(source)

        reconciliation = Counter()
        mismatch_examples = []
        for p in products.values():
            for m in p["monthly_sales"]:
                period = m["month"]
                # 2025+ are the period named by the transaction exports. Older rows are mostly adjustments.
                if "2025-01" <= period <= "2026-08":
                    monthly = m["quantity"] or 0
                    daily = event_totals.get((p["sku"], period), 0)
                    reconciliation["compared"] += 1
                    if abs(monthly - daily) < 1e-6:
                        reconciliation["matched"] += 1
                    else:
                        reconciliation["mismatched"] += 1
                        if len(mismatch_examples) < 12:
                            mismatch_examples.append(
                                dict(sku=p["sku"], month=period, monthly=monthly, event_net=daily)
                            )
            monthly_total = sum(m["quantity"] or 0 for m in p["monthly_sales"])
            if (
                p.get("reported_sales_total") is not None
                and abs(monthly_total - p["reported_sales_total"]) > 1e-6
            ):
                reconciliation["row_total_mismatches"] += 1
            p["company"] = company
            p["snapshot_date"] = "2026-09-22"
            db.execute("INSERT INTO products VALUES(?,?,?)", (company, p["sku"], store.dumps(p)))
        audit = dict(
            id=company,
            name=LABELS[company],
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            snapshot_date="2026-09-22",
            sources=sources,
            products=len(products),
            monthly_sales_products=sum(bool(p["monthly_sales"]) for p in products.values()),
            monthly_stock_products=sum(bool(p["monthly_stock"]) for p in products.values()),
            stock_snapshot_products=sum(p["stock"] is not None for p in products.values()),
            moq_products=sum(p["moq"] is not None for p in products.values()),
            pack_products=sum(p["pack_size"] is not None for p in products.values()),
            inbound_lines=sum(len(p["inbound"]) for p in products.values()),
            events=dict(event_stats),
            event_start=min(event_dates),
            event_end=max(event_dates),
            warehouses=dict(warehouses),
            reconciliation=dict(reconciliation),
            mismatch_examples=mismatch_examples,
            field_conflicts=conflicts[:30],
            seasonality=seasonality,
            returns_confirmed_by_user=True,
            limitations=[
                "Нет ID клиента: накладная не равна клиенту.",
                "Нет ежедневного наличия: месячный остаток не определяет stockout.",
                "Сентябрь 2026 неполный и не входит в backtest.",
                "Срок поставки, целевой сервис и период пересмотра вводятся вручную.",
                "Остатки без согласованной области складов нельзя смешивать с общими продажами.",
            ],
        )
        db.execute("INSERT INTO companies VALUES(?,?)", (company, store.dumps(audit)))
    return audit
