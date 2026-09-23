"""Manual inputs are explicit, versioned, and may not overwrite original Excel rows."""

import calendar
from datetime import date

from pydantic import Field, model_validator

from .schemas import Nonnegative, Positive, StrictModel


class MonthlyInput(StrictModel):
    month: str = Field(pattern=r"^20\d{2}-(0[1-9]|1[0-2])$")
    quantity: float | None = Field(default=None, ge=-1e9, le=1e9)
    excluded_quantity: Nonnegative = 0
    stockout_days: int = Field(default=0, ge=0, le=31)

    @model_validator(mode="after")
    def validate_month(self):
        d = date.fromisoformat(self.month + "-01")
        if self.stockout_days > calendar.monthrange(d.year, d.month)[1]:
            raise ValueError("Stockout days exceed calendar days")
        if self.excluded_quantity > max(self.quantity or 0, 0):
            raise ValueError("Excluded quantity exceeds recorded positive net sales")
        return self


class PartnerInbound(StrictModel):
    quantity: Positive
    eta: date
    reference: str = Field(default="Ручное поступление", max_length=250)


class PartnerMaterial(StrictModel):
    quantity: Positive
    due_date: date
    reference: str = Field(min_length=1, max_length=100)


class ManualProduct(StrictModel):
    expected_version: str | None = None
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=250)
    unit: str = Field(min_length=1, max_length=20)
    category: str | None = Field(default=None, max_length=100)
    supplier_sku: str | None = Field(default=None, max_length=100)
    snapshot_date: date
    stock: Nonnegative | None = None
    stock_date: date | None = None
    stock_scope_confirmed: bool = False
    purchase_price: Nonnegative | None = None
    moq: int | None = Field(default=None, ge=1, le=1000000)
    pack_size: int | None = Field(default=None, ge=1, le=100000)
    lead_days: int | None = Field(default=None, ge=1, le=120)
    review_days: int | None = Field(default=None, ge=1, le=60)
    service_level: float | None = Field(default=None, ge=0.8, le=0.995)
    growth_pct: float | None = Field(default=None, ge=-80, le=200)
    monthly_sales: list[MonthlyInput] = Field(max_length=120)
    inbound: list[PartnerInbound] = Field(default_factory=list, max_length=500)
    materials: list[PartnerMaterial] = Field(default_factory=list, max_length=500)
    note: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def validate_inputs(self):
        months = [r.month for r in self.monthly_sales]
        if len(months) != len(set(months)):
            raise ValueError("Duplicate monthly observation")
        if any(m > self.snapshot_date.strftime("%Y-%m") for m in months):
            raise ValueError("Historical sales cannot be after snapshot_date")
        if self.stock_date and self.stock_date > self.snapshot_date:
            raise ValueError("Stock snapshot is after calculation date")
        if not self.note.strip():
            raise ValueError("A reason for the manual change is required")
        return self


class PartnerCalculate(StrictModel):
    skus: list[str] = Field(default_factory=list, max_length=4000)
    limit: int = Field(default=100, ge=1, le=4000)
    offset: int = Field(default=0, ge=0)
