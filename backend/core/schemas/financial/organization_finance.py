from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal
from datetime import datetime

# ── Organization-level ────────────────────────────────────

class CounterpartResult(BaseModel):
    entity_afm: str
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    total_amount: Decimal
    decision_count: int
    avg_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    min_amount: Optional[Decimal] = None

class CounterpartPage(BaseModel):
    results: list[CounterpartResult]
    total_count: int
    has_more: bool

class RelationshipPairResult(BaseModel):
    organization_uid: str
    organization_label: Optional[str] = None
    entity_afm: str
    entity_name: Optional[str] = None
    entity_type: Optional[str] = None
    total_amount: Decimal
    decision_count: int

class RelationshipPairPage(BaseModel):
    results: list[RelationshipPairResult]
    total_count: int
    has_more: bool


class OrganizationAmountSummary(BaseModel):
    """Organization with financial aggregates for listing/leaderboard views."""
    uid: str
    label: Optional[str] = None
    count: int
    total_amount: float
    avg_amount: float = 0.0
    max_amount: float = 0.0
