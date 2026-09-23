"""Strict, versioned import contract. IDs must already be anonymized upstream."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

Positive = Annotated[float, Field(gt=0, le=1e9, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, le=1e9, allow_inf_nan=False)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.\-]+$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Category(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=120)
    service_level: float = Field(default=0.95, ge=0.8, le=0.995)
    review_days: int = Field(default=14, ge=1, le=60)


class Supplier(StrictModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=120)
    lead_days: int = Field(ge=1, le=120)


class Product(StrictModel):
    sku: Identifier
    name: str = Field(min_length=1, max_length=200)
    category_id: Identifier
    supplier_id: Identifier
    unit: str = Field(default="шт", max_length=20)
    purchase_price: Nonnegative
    pack_size: int = Field(default=1, ge=1, le=100000)
    moq: int = Field(default=1, ge=1, le=1000000)
    growth_pct: float = Field(default=0, ge=-80, le=200)


class Sale(StrictModel):
    date: date
    sku: Identifier
    warehouse: Identifier
    quantity: Positive
    price: Nonnegative
    client_id: str = Field(pattern=r"^anon_[a-zA-Z0-9_-]{3,64}$")


class Inventory(StrictModel):
    sku: Identifier
    warehouse: Identifier
    on_hand: Nonnegative


class Stockout(StrictModel):
    sku: Identifier
    warehouse: Identifier
    start: date
    end: date

    @model_validator(mode="after")
    def dates_ordered(self):
        if self.start > self.end:
            raise ValueError("stockout.start must be <= end")
        return self


class Inbound(StrictModel):
    sku: Identifier
    warehouse: Identifier
    quantity: Positive
    eta: date


class MaterialRequirement(StrictModel):
    """Unfulfilled incremental demand, not already reserved or counted in regular demand."""

    sku: Identifier
    warehouse: Identifier
    quantity: Positive
    due_date: date
    reference: Identifier


class Dataset(StrictModel):
    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    name: str = Field(min_length=1, max_length=120)
    synthetic: bool = False
    as_of: date
    history_start: date
    categories: list[Category] = Field(min_length=1, max_length=100)
    suppliers: list[Supplier] = Field(min_length=1, max_length=1000)
    products: list[Product] = Field(min_length=1, max_length=1000)
    sales: list[Sale] = Field(max_length=250000)
    inventory: list[Inventory] = Field(min_length=1, max_length=5000)
    stockouts: list[Stockout] = Field(default_factory=list, max_length=20000)
    inbound: list[Inbound] = Field(default_factory=list, max_length=20000)
    materials: list[MaterialRequirement] = Field(default_factory=list, max_length=20000)

    @model_validator(mode="after")
    def integrity(self):
        days = (self.as_of - self.history_start).days
        if not 28 <= days <= 3650:
            raise ValueError("History must contain 28–3650 completed days before as_of")
        for rows, key in [(self.categories, "id"), (self.suppliers, "id"), (self.products, "sku")]:
            ids = [getattr(r, key) for r in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {key}")
        skus = {p.sku for p in self.products}
        categories = {c.id for c in self.categories}
        suppliers = {s.id for s in self.suppliers}
        for p in self.products:
            if p.category_id not in categories or p.supplier_id not in suppliers:
                raise ValueError(f"Unknown category/supplier for {p.sku}")
        pairs = {(r.sku, r.warehouse) for r in self.inventory}
        if len(pairs) != len(self.inventory):
            raise ValueError("Duplicate inventory SKU/warehouse")
        if any(r.sku not in skus for r in self.inventory):
            raise ValueError("Unknown inventory SKU")
        for rows in [self.sales, self.stockouts, self.inbound, self.materials]:
            if any((r.sku, r.warehouse) not in pairs for r in rows):
                raise ValueError("Each source row must reference an existing inventory SKU/warehouse")
        if any(not self.history_start <= s.date < self.as_of for s in self.sales):
            raise ValueError("Sales dates must be in [history_start, as_of)")
        if any(s.start < self.history_start or s.end >= self.as_of for s in self.stockouts):
            raise ValueError("Stockouts must be in completed history")
        return self


class CalculateRequest(StrictModel):
    warehouse: str | None = None
    category_id: str | None = None
    growth_adjustment_pct: float = Field(default=0, ge=-80, le=200)
    review_days: int | None = Field(default=None, ge=1, le=60)
    service_level: float | None = Field(default=None, ge=0.8, le=0.995)


class OrderLine(StrictModel):
    sku: Identifier
    warehouse: Identifier
    quantity: int = Field(ge=0, le=1000000000)


class ApproveRequest(StrictModel):
    lines: list[OrderLine] = Field(min_length=1)
    note: str = Field(min_length=3, max_length=500)
    confirmed: bool
