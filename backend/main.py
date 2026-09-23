"""Local shared-workspace demo API with password accounts. No supplier send endpoint exists."""

import csv
import io
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from . import auth, storage
from .demo import make_demo
from .partner_api import router as partner_router
from .planning import calculate
from .schemas import ApproveRequest, CalculateRequest, Dataset


@asynccontextmanager
async def lifespan(app: FastAPI):
    if storage.latest_dataset() is None:
        storage.save_dataset(make_demo().model_dump(mode="json"))
    yield


app = FastAPI(
    title="WareSync · EKT Demand API",
    version="1.0.0",
    lifespan=lifespan,
    description="Локальный прототип: прогноз → рекомендация → ручное утверждение → CSV.",
)
app.include_router(partner_router)
app.include_router(auth.router)


@app.middleware("http")
async def request_limits(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.headers.get("X-WareSync-Request") != "1"
        ):
            return JSONResponse({"detail": "Запрос должен быть отправлен из WareSync"}, status_code=403)
        if request.url.path not in {"/api/health", "/api/auth/login", "/api/auth/register"}:
            user = await run_in_threadpool(auth.session_user, request)
            if user is None:
                return JSONResponse({"detail": "Войдите в аккаунт"}, status_code=401)
            request.state.user = user
    # Count actual streamed bytes too: Content-Length alone is not a trustworthy limit.
    if request.method in {"POST", "PUT", "PATCH"}:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32 * 1024 * 1024:
                return JSONResponse({"detail": "Размер импорта ограничен 32 МБ"}, status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def current() -> tuple[str, Dataset]:
    stored = storage.latest_dataset()
    if stored is None:
        raise HTTPException(404, "Загрузите набор данных")
    return stored[0], Dataset.model_validate(stored[1])


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "local-shared-workspace"}


@app.get("/api/dataset")
def dataset_summary(warehouse: str | None = None, category_id: str | None = None):
    identity, data = current()
    if warehouse and warehouse not in {i.warehouse for i in data.inventory}:
        raise HTTPException(422, "Неизвестный склад")
    if category_id and category_id not in {c.id for c in data.categories}:
        raise HTTPException(422, "Неизвестная категория")
    warehouse_skus = {i.sku for i in data.inventory if not warehouse or i.warehouse == warehouse}
    products = [
        p
        for p in data.products
        if (not category_id or p.category_id == category_id) and (not warehouse or p.sku in warehouse_skus)
    ]
    skus = {p.sku for p in products}
    supplier_ids = {p.supplier_id for p in products}
    sources = {
        name: sum(
            row.sku in skus and (not warehouse or row.warehouse == warehouse) for row in getattr(data, name)
        )
        for name in ["sales", "inventory", "stockouts", "inbound", "materials"]
    }
    sources["suppliers"] = len(supplier_ids)
    return dict(
        id=identity,
        name=data.name,
        synthetic=data.synthetic,
        as_of=data.as_of,
        history_start=data.history_start,
        sales_count=sources["sales"],
        products_count=len(products),
        warehouses=sorted({i.warehouse for i in data.inventory}),
        categories=data.categories,
        sources=sources,
    )


@app.get("/api/dataset/schema")
def import_schema():
    return Dataset.model_json_schema()


@app.get("/api/dataset/download")
def download_dataset():
    _, data = current()
    return Response(
        data.model_dump_json(),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="ekt-dataset.json"'},
    )


@app.post("/api/dataset")
def import_dataset(data: Dataset):
    return {
        "id": storage.save_dataset(data.model_dump(mode="json")),
        "message": "Данные проверены и сохранены",
    }


@app.post("/api/demo")
def reset_demo():
    return {"id": storage.save_dataset(make_demo().model_dump(mode="json"))}


@app.post("/api/runs")
def create_run(options: CalculateRequest):
    identity, data = current()
    if options.warehouse and options.warehouse not in {i.warehouse for i in data.inventory}:
        raise HTTPException(422, "Неизвестный склад")
    if options.category_id and options.category_id not in {c.id for c in data.categories}:
        raise HTTPException(422, "Неизвестная категория")
    return storage.save_run(identity, calculate(data, options))


@app.get("/api/runs")
def run_list(warehouse: str | None = None, category_id: str | None = None, dataset_id: str | None = None):
    return storage.list_runs(warehouse=warehouse, category_id=category_id, dataset_id=dataset_id)


@app.get("/api/runs/{identity}")
def run_detail(identity: str):
    result = storage.get_run(identity)
    if result is None:
        raise HTTPException(404, "Расчёт не найден")
    return result


@app.post("/api/runs/{identity}/approve")
def approve_run(identity: str, request: ApproveRequest):
    run = run_detail(identity)
    if not request.confirmed:
        raise HTTPException(422, "Требуется явное подтверждение сотрудника")
    expected = {(r["sku"], r["warehouse"]): r for r in run["rows"]}
    actual = {(r.sku, r.warehouse): r.quantity for r in request.lines}
    if len(actual) != len(request.lines) or set(actual) != set(expected):
        raise HTTPException(422, "Передайте каждую позицию расчёта ровно один раз, включая нулевые")
    for key, quantity in actual.items():
        row = expected[key]
        if quantity and (quantity < row["moq"] or quantity % row["pack_size"]):
            raise HTTPException(422, f"{row['sku']}: количество должно соблюдать MOQ и кратность упаковки")
    if not any(actual.values()):
        raise HTTPException(422, "В заказе должна быть хотя бы одна ненулевая позиция")
    approval = dict(
        at=storage.now(),
        note=request.note,
        lines=[r.model_dump() for r in request.lines],
        amount=round(sum(actual[k] * expected[k]["price"] for k in actual), 2),
    )
    if not storage.approve(identity, approval):
        raise HTTPException(409, "Расчёт уже утверждён; создайте новый для изменений")
    return run_detail(identity)


def safe_cell(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else text


@app.get("/api/runs/{identity}/export")
def export_run(identity: str):
    run = run_detail(identity)
    quantities = (
        {(r["sku"], r["warehouse"]): r["quantity"] for r in run["approval"]["lines"]}
        if run["approval"]
        else {}
    )
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "Статус",
            "Артикул",
            "Наименование",
            "Склад",
            "Поставщик",
            "Количество",
            "Ед.",
            "ЦенаЗакупки",
            "Сумма",
            "Срочность",
            "Обоснование",
            "Комментарий",
            "РасчетID",
        ]
    )
    for row in sorted(run["rows"], key=lambda r: (r["supplier"], r["sku"], r["warehouse"])):
        q = quantities.get((row["sku"], row["warehouse"]), row["quantity"])
        if q <= 0:
            continue
        writer.writerow(
            [
                safe_cell(v)
                for v in [
                    "Утверждён" if run["approval"] else "Черновик",
                    row["sku"],
                    row["name"],
                    row["warehouse"],
                    row["supplier"],
                    q,
                    row["unit"],
                    str(row["price"]).replace(".", ","),
                    str(round(q * row["price"], 2)).replace(".", ","),
                    row["urgency"],
                    row["explanation"],
                    run["approval"]["note"] if run["approval"] else "",
                    identity,
                ]
            ]
        )
    return Response(
        content="\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ekt-{run["status"]}-{identity[:8]}.csv"'},
    )


dist = Path(__file__).resolve().parents[1] / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def frontend():
        return FileResponse(dist / "index.html")
