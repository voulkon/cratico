from datetime import date
from typing import List, Optional

from pydantic import AnyUrl, BaseModel, Field


# Models for company data
class Announcement(BaseModel):
    """Details of an announcement related to a company organ decision."""

    decision_date: date = Field(alias="decisionDate")
    subject: str = Field(alias="decisionSubject")
    announcement_date: date = Field(alias="announcementDate")
    announcement_file: Optional[AnyUrl] = Field(
        None, alias="announcementFile", description="URL of the announcement document"
    )
    completion_date: Optional[date] = Field(None, alias="completionDate")


class OrganDecision(BaseModel):
    """Represents a decision by a company organ (e.g., Board or General Meeting) with related publication info."""

    decision_date: date = Field(alias="decisionDate")
    organ_type: str = Field(
        alias="organType"
    )  # e.g., type of organ (Board, General Assembly):contentReference[oaicite:9]{index=9}
    protocol_number: Optional[str] = Field(None, alias="protocolNumber")
    submission_date: Optional[date] = Field(None, alias="submissionDate")
    minutes_text: Optional[str] = Field(
        None, alias="minutes", description="Minutes of the meeting (if available)"
    )
    decision_summary: Optional[str] = Field(None, alias="decisionSummary")
    invitation_posted: Optional[bool] = Field(
        None, alias="invitationPost", description="Whether an invitation was posted"
    )
    invitation_post_date: Optional[date] = Field(None, alias="invitationPostDate")
    publication: Optional[str] = Field(
        None, alias="publicationPaper", description="Newspaper or medium of publication"
    )
    publication_date: Optional[date] = Field(None, alias="publicationPaperDate")
    announcements: Optional[List[Announcement]] = Field(
        alias="announcementRecords", default_factory=list
    )


class PublicDocument(BaseModel):
    """Represents a public document filed for the company (e.g., filings, certificates)."""

    document_id: Optional[str] = Field(None, alias="documentId")
    document_type: Optional[str] = Field(None, alias="documentType")
    title: Optional[str] = Field(None, alias="title")
    publish_date: Optional[date] = Field(None, alias="date")
    url: Optional[AnyUrl] = Field(
        None, alias="url", description="Download link for the document"
    )


class CompanyDetail(BaseModel):
    """Full public profile of a company from the GEMI OpenData API."""

    gemh_number: str = Field(alias="gemhNumber")
    name: str = Field(alias="name")
    trade_name: Optional[str] = Field(None, alias="distinctiveTitle")
    vat_number: Optional[str] = Field(
        None, alias="afm"
    )  # 'afm' (Greek Tax ID):contentReference[oaicite:10]{index=10}
    local_office: Optional[str] = Field(
        None, alias="gemiOffice", description="Name of the local GEMI service"
    )
    status: Optional[str] = Field(None, alias="status")
    registration_date: Optional[date] = Field(
        None, alias="registrationDate", description="Date of GEMI registration"
    )
    publicity_documents: List[PublicDocument] = Field(
        alias="publicityDocuments", default_factory=list
    )
    organ_decisions: List[OrganDecision] = Field(
        alias="organDecisions", default_factory=list
    )


class CompanySummary(BaseModel):
    """Summary information for a company (used in search results)."""

    gemh_number: str = Field(alias="gemhNumber")
    name: str = Field(alias="name")
    trade_name: Optional[str] = Field(None, alias="distinctiveTitle")
    vat_number: Optional[str] = Field(None, alias="afm")
    status: Optional[str] = Field(None, alias="status")


# Models for reference (parametric) data lists
class LocalOffice(BaseModel):
    """A local GEMI registry office (Chamber)."""

    id: int
    name: str


class Prefecture(BaseModel):
    """A regional unit (nomos) for company location."""

    id: int
    name: str


class Municipality(BaseModel):
    """A municipality for company location."""

    id: int
    name: str


class BusinessStatus(BaseModel):
    """A possible status of a business (e.g., Active, Inactive)."""

    id: int
    name: str


class LegalForm(BaseModel):
    """A legal form of a company (e.g., SA, LLC, sole proprietorship)."""

    id: int
    name: str


class OrganType(BaseModel):
    """Type of company organ (e.g., Board of Directors, General Meeting)."""

    id: int
    name: str


class DocumentType(BaseModel):
    """Type of public document in GEMI (e.g., Announcement, Decision)."""

    id: int
    name: str


class DecisionType(BaseModel):
    """Type of company decision (category of decisions in GEMI)."""

    id: int
    name: str
