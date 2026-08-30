"""
Pydantic schemas for the decision detail endpoint.

These models mirror the dict structure returned by
``api.views.decisions.details.decision_detail`` so the view can use
``api.utils.response.pydantic_response`` instead of returning a plain dict.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


# ── Nested models ──────────────────────────────────────────────


class OrganizationInfo(BaseModel):
    uid: str
    label: str
    latin_name: Optional[str] = None
    category: Optional[str] = None


class DecisionTypeInfo(BaseModel):
    uid: str
    label: str


class SignerInfo(BaseModel):
    uid: str
    first_name: str
    last_name: str
    active: bool = True
    has_organization_sign_rights: bool = False


class UnitInfo(BaseModel):
    uid: str
    label: str
    active: bool = True
    category: Optional[str] = None


class KaeAmount(BaseModel):
    kae: str
    amount: float


class AttachmentInfo(BaseModel):
    attachment_id: str
    filename: str
    mime_type: Optional[str] = None
    description: Optional[str] = None
    checksum: Optional[str] = None


class AIAnalysisInfo(BaseModel):
    status: Optional[str] = None
    summary: Optional[str] = None
    cost_usd: Optional[str] = None
    model_used: Optional[str] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


# ── Top-level response ─────────────────────────────────────────


class DecisionDetailResponse(BaseModel):
    id: int
    ada: Optional[str] = None
    version_id: Optional[str] = None
    corrected_version_id: Optional[str] = None
    protocol_number: Optional[str] = None
    subject: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    financial_year: Optional[int] = None
    issue_date: Optional[date] = None
    publish_timestamp: Optional[datetime] = None
    submission_timestamp: Optional[datetime] = None
    status: Optional[str] = None
    document_url: Optional[str] = None
    document_checksum: Optional[str] = None
    url: Optional[str] = None
    diavgeia_page_url: Optional[str] = None
    diavgeia_doc_url: Optional[str] = None
    has_document_content: bool = False
    ai_analyses: list[AIAnalysisInfo] = []
    warnings: Optional[list] = None
    has_private_data: bool = False
    organization: Optional[OrganizationInfo] = None
    decision_type: Optional[DecisionTypeInfo] = None
    signers: list[SignerInfo] = []
    units: list[UnitInfo] = []
    kae_amounts: list[KaeAmount] = []
    attachments: list[AttachmentInfo] = []
    thematic_category_ids: Optional[list] = None
    # Amount correction state (for the "verify amount" UI knob)
    has_corrected_amounts: bool = False
    corrected_amount: Optional[float] = None
