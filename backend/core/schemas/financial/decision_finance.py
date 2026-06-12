from pydantic import BaseModel
from typing import Optional
from decimal import Decimal
from .entity_finance import EntityInfo
# ── Decision-level ────────────────────────────────────────

class EntityAmount(BaseModel):
    entity: EntityInfo
    role: str
    total_amount: Decimal
    amount_count: int

class DecisionAmountBreakdown(BaseModel):
    decision_ada: str
    linked_total: Decimal
    unlinked_total: Decimal
    total_amount: Decimal
    entity_count: int
    has_entities: bool
    has_unlinked_amounts: bool
    all_amounts_linked: bool

class AmountConsistency(BaseModel):
    decision_ada: str
    total_from_amount_fields: Decimal
    linked_amounts_total: Decimal
    unlinked_amounts_total: Decimal
    decision_amount_field: Decimal
    kae_total: Decimal
    discrepancy: Optional[Decimal] = None
    discrepancy_percentage: Optional[float] = None
    is_consistent: bool
