from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReferenceItem(BaseModel):
    """Base schema for reference data items with id and description."""

    id: int
    descr: str


class Municipality(ReferenceItem):
    """Municipality reference data."""


class Prefecture(ReferenceItem):
    """Prefecture reference data."""


class LegalType(ReferenceItem):
    """Legal type reference data."""


class GemiOffice(ReferenceItem):
    """GEMI office reference data."""


class AssemblySubjects(ReferenceItem):
    """Assembly subjects reference data."""


class Status(ReferenceItem):
    """Company status reference data."""


class Activity(BaseModel):
    """Company activity details."""

    id: str
    descr: str


class CompanyActivity(BaseModel):
    """Company activity with type and date range."""

    activity: Activity
    type: str
    dtFrom: Optional[str] = None
    dtTo: Optional[str] = None


class Person(BaseModel):
    """Person associated with the company."""

    personName: Optional[str] = None
    businessName: Optional[str] = None
    role: Optional[str] = None
    dtFrom: Optional[str] = None
    dtTo: Optional[str] = None
    isRepresentativeAlone: Optional[bool] = None
    isRepresentativeInCommon: Optional[bool] = None


class Capital(BaseModel):
    """Company capital information."""

    capitalStock: Optional[float] = None
    currency: Optional[str] = None
    ecsokefalaiikes: Optional[float] = None
    eggiitikes: Optional[float] = None


class Stock(BaseModel):
    """Company stock information."""

    stockTypeId: Optional[int] = None
    amount: Optional[float] = None
    nominalPrice: Optional[float] = None
    stockType: Optional[str] = None


class CompanyResponse(BaseModel):
    """Complete company information response from GEMI API."""

    # Basic company information
    arGemi: int = Field(..., description="GEMI registration number")
    afm: Optional[str] = Field(None, description="Tax identification number (AFM)")
    coNameEl: Optional[str] = Field(None, description="Company name in Greek")
    coNamesEn: Optional[List[str]] = Field(
        default_factory=list, description="Company names in English"
    )
    coTitlesEl: Optional[List[str]] = Field(
        default_factory=list, description="Company titles in Greek"
    )
    coTitlesEn: Optional[List[str]] = Field(
        default_factory=list, description="Company titles in English"
    )

    # Location information
    municipality: Optional[Municipality] = None
    prefecture: Optional[Prefecture] = None
    city: Optional[str] = None
    street: Optional[str] = None
    streetNumber: Optional[str] = None
    zipCode: Optional[str] = None
    poBox: Optional[str] = None

    # Contact information
    url: Optional[str] = None
    email: Optional[str] = None

    # Company details
    isBranch: Optional[bool] = None
    objective: Optional[str] = Field(None, description="Company business objective")
    legalType: Optional[LegalType] = None
    gemiOffice: Optional[GemiOffice] = None
    assemblySubjects: Optional[AssemblySubjects] = None

    # Dates and status
    incorporationDate: Optional[str] = None
    lastStatusChange: Optional[str] = None
    status: Optional[Status] = None
    autoRegistered: Optional[bool] = None

    # Complex nested data
    activities: Optional[List[CompanyActivity]] = Field(default_factory=list)
    persons: Optional[List[Person]] = Field(default_factory=list)
    capital: Optional[List[Capital]] = Field(default_factory=list)
    stocks: Optional[List[Stock]] = Field(default_factory=list)
    branch: Optional[List[int]] = Field(
        default_factory=list, description="Branch GEMI numbers"
    )

    @field_validator("arGemi")
    @classmethod
    def validate_ar_gemi(cls, v):
        """Validate that arGemi is a positive integer."""
        if v <= 0:
            raise ValueError("arGemi must be a positive integer")
        return v

    @field_validator("afm")
    @classmethod
    def validate_afm(cls, v):
        """Validate AFM format if provided."""
        if v is not None and v.strip():
            # Remove any spaces or special characters
            clean_afm = "".join(filter(str.isdigit, v))
            if len(clean_afm) != 9:
                raise ValueError("AFM must be exactly 9 digits")
            return clean_afm
        return v

    model_config = ConfigDict(extra="ignore", validate_assignment=True)


class CompanyStatus(BaseModel):
    """Company status reference data."""

    id: int
    descr: Optional[str] = None


class CompanySummary(BaseModel):
    """Summary information for a company (used in search results)."""

    gemh_number: str = Field(alias="arGemi")
    name: str = Field(alias="coNameEl")
    trade_name: Optional[str] = Field(default=None, alias="distinctiveTitle")
    vat_number: Optional[str] = Field(None, alias="afm")
    status: Optional[CompanyStatus] = Field(default=None)
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
