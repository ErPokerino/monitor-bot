"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from monitor_bot.db_models import Evaluation, RunStatus, SourceCategory, SourceType


# ------------------------------------------------------------------
# MonitoredSource
# ------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2048)
    category: SourceCategory
    source_type: SourceType


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    category: SourceCategory | None = None
    source_type: SourceType | None = None
    is_active: bool | None = None


class SourceOut(BaseModel):
    id: int
    name: str
    url: str
    category: SourceCategory
    source_type: SourceType
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------
# SearchQuery
# ------------------------------------------------------------------

class QueryCreate(BaseModel):
    query_text: str = Field(min_length=1, max_length=1024)
    category: SourceCategory
    max_results: int = Field(default=5, ge=1, le=50)


class QueryUpdate(BaseModel):
    query_text: str | None = None
    category: SourceCategory | None = None
    max_results: int | None = None
    is_active: bool | None = None


class QueryOut(BaseModel):
    id: int
    query_text: str
    category: SourceCategory
    max_results: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------
# SearchRun
# ------------------------------------------------------------------

class RunOut(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    total_collected: int
    total_classified: int
    total_relevant: int
    elapsed_seconds: float | None

    model_config = {"from_attributes": True}


class ResultOut(BaseModel):
    id: int
    run_id: int
    opportunity_id: str
    title: str
    description: str
    contracting_authority: str
    deadline: date | None
    estimated_value: float | None
    currency: str
    country: str
    source_url: str
    source: str
    opportunity_type: str
    relevance_score: int
    category: str
    ai_reasoning: str
    key_requirements: str
    event_format: str | None = None
    event_cost: str | None = None
    city: str | None = None
    sector: str | None = None

    model_config = {"from_attributes": True}


class RunDetailOut(RunOut):
    results: list[ResultOut] = []


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

class DashboardOut(BaseModel):
    active_sources: int
    total_sources: int
    active_queries: int
    total_queries: int
    last_run: RunOut | None
    recent_runs: list[RunOut]
    is_running: bool


# ------------------------------------------------------------------
# Agenda
# ------------------------------------------------------------------

class AgendaItemOut(BaseModel):
    id: int
    source_url: str
    opportunity_id: str
    title: str
    description: str
    contracting_authority: str
    deadline: date | None
    estimated_value: float | None
    currency: str
    country: str
    source: str
    opportunity_type: str
    relevance_score: int
    category: str
    ai_reasoning: str
    key_requirements: str
    event_format: str | None = None
    event_cost: str | None = None
    city: str | None = None
    sector: str | None = None
    evaluation: Evaluation | None
    is_enrolled: bool
    feedback_recommend: bool | None
    feedback_return: bool | None
    is_seen: bool
    first_seen_at: datetime
    evaluated_at: datetime | None

    model_config = {"from_attributes": True}


class AgendaEvaluateRequest(BaseModel):
    evaluation: Evaluation


class AgendaEnrollRequest(BaseModel):
    is_enrolled: bool


class AgendaFeedbackRequest(BaseModel):
    recommend: bool
    return_next_year: bool


class AgendaMarkSeenRequest(BaseModel):
    ids: list[int] | None = None
    all: bool = False


class AgendaStatsOut(BaseModel):
    unseen_count: int
    pending_count: int
    expiring_count: int


# ------------------------------------------------------------------
# Batch operations
# ------------------------------------------------------------------

class BatchDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


class BatchDeleteResponse(BaseModel):
    deleted: int
