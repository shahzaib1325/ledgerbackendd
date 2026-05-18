"""Global search response schemas."""

from __future__ import annotations
from decimal import Decimal
from pydantic import BaseModel


class SearchResultItem(BaseModel):
    entity_type: str      # customer | supplier | staff | item | sale | purchase
    id: int
    name: str
    subtitle: str | None  # phone, SKU, invoice_no, department, etc.
    meta: dict            # balance, status, stock, amount — flexible per type
    href: str             # frontend navigation path


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    total: int
