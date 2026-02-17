"""Domain models shared across the application."""

from __future__ import annotations

import enum
from datetime import date

from pydantic import BaseModel, Field


class Source(str, enum.Enum):
    """Where the opportunity was collected from."""

    TED = "TED"
    ANAC = "ANAC"
    EVENT = "Event"
    REGIONALE = "Regionale"
    WEB_SEARCH = "WebSearch"


class OpportunityType(str, enum.Enum):
    """High-level type of opportunity for filtering."""

    BANDO = "Bando"
    CONCORSO = "Concorso"
    EVENTO = "Evento"


class Category(str, enum.Enum):
    """Business-area categories the classifier can assign."""

    SAP = "SAP"
    DATA = "Data"
    AI = "AI"
    CLOUD = "Cloud"
    OTHER = "Other"


class Opportunity(BaseModel):
    """A normalised public-procurement opportunity."""

    id: str = Field(description="Unique identifier from the source system")
    title: str
    description: str = ""
    contracting_authority: str = ""
    deadline: date | None = None
    estimated_value: float | None = None
    currency: str = "EUR"
    country: str = ""
    source_url: str = ""
    source: Source
    opportunity_type: OpportunityType = OpportunityType.BANDO
    publication_date: date | None = None
    cpv_codes: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    """Structured output returned by Gemini for a single opportunity."""

    relevance_score: int = Field(ge=1, le=10, description="1-10 relevance score")
    category: Category
    reason: str = Field(description="Brief motivation for the score")
    key_requirements: list[str] = Field(
        default_factory=list,
        description="Key requirements extracted from the tender",
    )
    extracted_date: str | None = Field(
        default=None,
        description=(
            "Relevant date extracted from the text in ISO format (YYYY-MM-DD). "
            "For events: the event date. For tenders: the submission deadline."
        ),
    )


class ClassifiedOpportunity(BaseModel):
    """An opportunity enriched with its AI classification."""

    opportunity: Opportunity
    classification: Classification

    # Convenience accessors
    @property
    def score(self) -> int:
        return self.classification.relevance_score

    @property
    def category(self) -> Category:
        return self.classification.category
