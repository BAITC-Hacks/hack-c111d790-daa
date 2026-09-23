"""Partner workspace API: read-only originals, audited manual inputs and saved forecasts."""

import csv
import io
import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from . import partner_store as store
from .partner_forecast import VERSION, run_product
from .partner_import import empty_product
from .partner_models import ManualProduct, PartnerCalculate
from .storage import digest, now

router = APIRouter(prefix="/api/partners", tags=["Partner data"])


def company_or_404(company):
    value = store.get_company(company)
    if value is None:
        raise HTTPException(404, "Архив компании ещё не импортирован")
    return value


@router.get("")
def companies():
    return store.companies()


@router.get("/{company}/products")
def products(
    company: str,
    search: str = "",
    limit: int = Query(default=100, ge=1, le=4000),
    offset: int = Query(default=0, ge=0),
):
    company_or_404(company)
    rows = [
        p
        for p in store.all_products(company)
        if search.casefold() in f"{p['sku']} {p['name']} {p['supplier_sku'] or ''}".casefold()
    ]
    rows.sort(key=lambda p: (not bool(p["monthly_sales"]), p["name"]))
    return dict(
        total=len(rows),
        items=[
            {
                k: p[k]
                for k in ["sku", "name", "unit", "supplier_sku", "category", "stock", "moq", "pack_size"]
            }
            | {"has_history": bool(p["monthly_sales"])}
            for p in rows[offset : offset + limit]
        ],
    )


@router.get("/{company}/product")
def product_detail(company: str, sku: str):
    p = store.get_product(company, sku)
    if p is None:
        raise HTTPException(404, "SKU не найден")
    with store.connect() as db:
        events = db.execute(
            """SELECT COUNT(*) n, SUM(CASE WHEN quantity<0 THEN quantity ELSE 0 END) returns,
                             SUM(CASE WHEN quantity>0 THEN quantity ELSE 0 END) gross FROM events WHERE company=? AND sku=?""",
            (company, sku),
        ).fetchone()
        largest = [
            dict(r)
            for r in db.execute(
                "SELECT date,warehouse,document,SUM(quantity) quantity FROM events WHERE company=? AND sku=? AND quantity>0 GROUP BY date,warehouse,document ORDER BY quantity DESC LIMIT 8",
                (company, sku),
            )
        ]
        revisions = [
            dict(r)
            for r in db.execute(
                "SELECT id,created_at,note FROM revisions WHERE company=? AND sku=? ORDER BY id DESC",
                (company, sku),
            )
        ]
    return p | {
        "version": digest(p),
        "event_summary": dict(events),
        "largest_documents": largest,
        "revisions": revisions,
    }


@router.post("/{company}/manual")
def save_manual(company: str, request: ManualProduct):
    company_or_404(company)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT payload FROM products WHERE company=? AND sku=?", (company, request.sku)
        ).fetchone()
        old = json.loads(existing[0]) if existing else None
        if (old and request.expected_version != digest(old)) or (
            not old and request.expected_version is not None
        ):
            raise HTTPException(409, "Данные изменились. Откройте карточку заново перед сохранением.")
        p = old.copy() if old else empty_product(request.sku)
        changes = request.model_dump(mode="json", exclude={"expected_version", "note"})
        timestamp = now()
        p.update(changes)
        p.update(company=company, manual_note=request.note)
        p["provenance"] = dict(p["provenance"])
        for field, value in changes.items():
            if old is None or old.get(field) != value:
                p["provenance"][field] = f"Ручной ввод {timestamp}: {request.note}"
        db.execute("INSERT OR REPLACE INTO products VALUES(?,?,?)", (company, p["sku"], store.dumps(p)))
        db.execute(
            "INSERT INTO revisions(company,sku,created_at,note,before_json,after_json) VALUES(?,?,?,?,?,?)",
            (company, p["sku"], timestamp, request.note, store.dumps(old), store.dumps(p)),
        )
    return product_detail(company, request.sku)


def calculate_company(company, request):
    metadata = company_or_404(company)
    items = store.all_products(company)
    if request.skus:
        if len(request.skus) != len(set(request.skus)):
            raise HTTPException(422, "Повторяющиеся SKU")
        index = {p["sku"]: p for p in items}
        if any(s not in index for s in request.skus):
            raise HTTPException(422, "Неизвестный SKU")
        selected = [index[s] for s in request.skus]
    else:
        items.sort(key=lambda p: (not bool(p["monthly_sales"]), p["sku"]))
        selected = items[request.offset : request.offset + request.limit]
    rows = [run_product(p, metadata) | {"input_version": digest(p)} for p in selected]
    valid = [r for r in rows if r["metrics"] and r["metrics"]["samples"]]
    # Portfolio quantity WAPE is separated by unit; never add metres and pieces.
    by_unit = {}
    for unit in sorted({r["unit"] or "не указана" for r in valid}):
        group = [r for r in valid if (r["unit"] or "не указана") == unit]
        denom = sum(r["metrics"]["actual_sum"] for r in group)
        by_unit[unit] = dict(
            positions=len(group),
            actual_sum=round(denom, 2),
            wape=round(sum(r["metrics"]["absolute_error_sum"] for r in group) / denom * 100, 2)
            if denom
            else None,
            baseline_wape=round(sum(r["baseline"]["absolute_error_sum"] for r in group) / denom * 100, 2)
            if denom
            else None,
        )
    result = dict(
        id=uuid4().hex,
        created_at=now(),
        company=company,
        company_name=metadata["name"],
        model_version=VERSION,
        source="partner-files",
        rows=rows,
        summary=dict(
            positions=len(rows),
            evaluated=len(valid),
            orders_ready=sum(r["quantity"] is not None for r in rows),
            needs_inputs=sum(bool(r["blocked"]) for r in rows),
            by_unit=by_unit,
        ),
        input_snapshots=selected,
        archive_sha256=metadata["archive_sha256"],
        evaluation_scope="Чистые месячные отгрузки; неизвестные stockout и разовые клиенты не размечены. Не метрика скрытого спроса.",
    )
    with store.connect() as db:
        db.execute(
            "INSERT INTO partner_runs VALUES(?,?,?,?)",
            (result["id"], result["created_at"], company, store.dumps(result)),
        )
    return {k: v for k, v in result.items() if k != "input_snapshots"}


@router.post("/{company}/calculate")
def calculate(company: str, request: PartnerCalculate):
    return calculate_company(company, request)


@router.get("/{company}/runs")
def runs(company: str):
    company_or_404(company)
    with store.connect() as db:
        records = db.execute(
            "SELECT payload FROM partner_runs WHERE company=? ORDER BY created_at DESC LIMIT 20", (company,)
        ).fetchall()
    return [
        {k: v for k, v in json.loads(r[0]).items() if k in ["id", "created_at", "company", "summary"]}
        for r in records
    ]


@router.get("/{company}/runs/{identity}")
def get_run(company: str, identity: str):
    with store.connect() as db:
        r = db.execute(
            "SELECT payload FROM partner_runs WHERE id=? AND company=?", (identity, company)
        ).fetchone()
    if r is None:
        raise HTTPException(404, "Расчёт не найден")
    return {k: v for k, v in json.loads(r[0]).items() if k != "input_snapshots"}


@router.get("/{company}/runs/{identity}/export")
def export(company: str, identity: str):
    result = get_run(company, identity)
    out = io.StringIO(newline="")
    w = csv.writer(out, delimiter=";")
    w.writerow(
        [
            "Компания",
            "Код1С",
            "Артикул",
            "Наименование",
            "Единица",
            "Модель",
            "ПрогнозМесяц1",
            "КЗаказу",
            "Сумма",
            "WAPE",
            "НедостающиеДанные",
            "Обоснование",
            "Статус",
        ]
    )
    for r in result["rows"]:
        values = [
            company,
            r["sku"],
            r["supplier_sku"],
            r["name"],
            r["unit"],
            r["model"],
            r["forecast"][0]["quantity"] if r["forecast"] else None,
            r["quantity"],
            r["amount"],
            r["metrics"]["wape"] if r["metrics"] else None,
            "; ".join(r["blocked"]),
            r.get("explanation"),
            "Черновик / ручная проверка",
        ]
        w.writerow(
            [
                ("'" + str(v)) if str(v).lstrip().startswith(("=", "+", "-", "@")) else "" if v is None else v
                for v in values
            ]
        )
    return Response(
        "\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{company}-{identity[:8]}.csv"'},
    )
