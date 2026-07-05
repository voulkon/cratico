from .entity_finance import (
    EntityFinancialSummary, EntityInfo, 
    RoleBreakdown, OrgBreakdown, EntityDateRange,
    )
from .organization_finance import (
    CounterpartResult, CounterpartPage, 
    RelationshipPairResult, RelationshipPairPage,
    OrganizationAmountSummary,
    OrganizationCounterpartResult,
    OrganizationCounterpartPage
    )
from .decision_finance import (
    AmountConsistency,
    DecisionAmountBreakdown,
    EntityAmount,
    DecisionTypeBreakdown,
)
from pydantic import BaseModel, Field
from decimal import Decimal

class TimelinePoint(BaseModel):
    period: str              # "2025-06" (month) or "2025" (year) or "2025-06-13" (day)
    total_amount: float
    decision_count: int

class GlobalFinancialSummary(BaseModel):
    total_amount: Decimal
    total_decisions: int
    avg_amount: Decimal
    legacy_total_amount: Decimal
    calculation_method: str = "relationship_based"
    accuracy_improvement: Decimal
