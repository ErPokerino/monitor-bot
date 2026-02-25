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


class EventFormat(str, enum.Enum):
    """Whether the event is in-person, streamed, or on-demand."""

    IN_PRESENZA = "In presenza"
    STREAMING = "Streaming"
    ON_DEMAND = "On demand"


class EventCost(str, enum.Enum):
    """Admission cost model for an event."""

    GRATUITO = "Gratuito"
    A_PAGAMENTO = "A pagamento"
    SU_INVITO = "Su invito"


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
    event_format: EventFormat | None = Field(
        default=None,
        description="In presenza / Streaming / On demand (only for events).",
    )
    event_cost: EventCost | None = Field(
        default=None,
        description="Gratuito / A pagamento / Su invito (only for events).",
    )
    city: str | None = Field(
        default=None,
        description="City where the event takes place (only for in-person events).",
    )
    sector: str | None = Field(
        default=None,
        description="Industry sector targeted by the opportunity (e.g. Healthcare, Finance, PA).",
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
