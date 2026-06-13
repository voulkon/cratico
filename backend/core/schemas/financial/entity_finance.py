from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal
from datetime import date, datetime

# ── Entity-level ──────────────────────────────────────────

class EntityInfo(BaseModel):
    afm: str
    name: Optional[str] = None
    entity_type: Optional[str] = None
    total_appearances: Optional[int] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

class RoleBreakdown(BaseModel):
    role: str
    total_amount: Decimal
    decision_count: int

class OrgBreakdown(BaseModel):
    organization_uid: str
    organization_label: Optional[str] = None
    total_amount: Decimal
    decision_count: int

class EntityFinancialSummary(BaseModel):
    entity: EntityInfo
    total_received: Decimal
    decision_count: int
    avg_amount: Decimal
    unique_organizations: int
    top_organizations: list[OrgBreakdown] = Field(default_factory=list)
    role_breakdown: list[RoleBreakdown] = Field(default_factory=list)


class EntityDateRange(BaseModel):
    """Date range and activity overview for a single entity."""
    earliest_date: Optional[date] = None
    latest_date: Optional[date] = None
    span_days: int = 0
    recommended_granularity: str = "month"
    total_decisions: int = 0
    total_amount: float = 0.0
    avg_daily_decisions: float = 0.0
    avg_daily_amount: float = 0.0