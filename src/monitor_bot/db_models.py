"""SQLAlchemy ORM models for the web application."""

from __future__ import annotations

import enum
from datetime import date, datetime

import zoneinfo

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from monitor_bot.database import Base

_ROME = zoneinfo.ZoneInfo("Europe/Rome")


def _now_rome() -> datetime:
    return datetime.now(_ROME).replace(tzinfo=None)


# ------------------------------------------------------------------
# Enums
# ------------------------------------------------------------------

class SourceCategory(str, enum.Enum):
    EVENTI = "eventi"
    BANDI = "bandi"
    FONDI = "fondi"


class SourceType(str, enum.Enum):
    RSS_FEED = "rss_feed"
    WEB_PAGE = "web_page"
    TENDER_PORTAL = "tender_portal"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Evaluation(str, enum.Enum):
    INTERESTED = "interested"
    REJECTED = "rejected"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


# ------------------------------------------------------------------
# Tables
# ------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_reset_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_rome, onupdate=_now_rome, nullable=False,
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)


class MonitoredSource(Base):
    __tablename__ = "monitored_sources"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "url", name="uq_monitored_sources_owner_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    category: Mapped[SourceCategory] = mapped_column(Enum(SourceCategory), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_rome, onupdate=_now_rome, nullable=False,
    )


class SearchQuery(Base):
    __tablename__ = "search_queries"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "query_text", name="uq_search_queries_owner_text"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    query_text: Mapped[str] = mapped_column(String(1024), nullable=False)
    category: Mapped[SourceCategory] = mapped_column(Enum(SourceCategory), nullable=False)
    max_results: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now_rome, onupdate=_now_rome, nullable=False,
    )


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), default=RunStatus.RUNNING, nullable=False,
    )
    total_collected: Mapped[int] = mapped_column(Integer, default=0)
    total_classified: Mapped[int] = mapped_column(Integer, default=0)
    total_relevant: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list[SearchResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin",
    )


class SearchResult(Base):
    __tablename__ = "search_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("search_runs.id"), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    opportunity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    contracting_authority: Mapped[str] = mapped_column(String(512), default="")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    country: Mapped[str] = mapped_column(String(10), default="")
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_reasoning: Mapped[str] = mapped_column(Text, default="")
    key_requirements: Mapped[str] = mapped_column(Text, default="")
    event_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_cost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)

    run: Mapped[SearchRun] = relationship(back_populates="results")


class AgendaItem(Base):
    __tablename__ = "agenda_items"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "source_url", name="uq_agenda_items_owner_source_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    contracting_authority: Mapped[str] = mapped_column(String(512), default="")
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="EUR")
    country: Mapped[str] = mapped_column(String(10), default="")
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    relevance_score: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    ai_reasoning: Mapped[str] = mapped_column(Text, default="")
    key_requirements: Mapped[str] = mapped_column(Text, default="")
    event_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event_cost: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)

    evaluation: Mapped[Evaluation | None] = mapped_column(Enum(Evaluation), nullable=True)
    is_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    feedback_recommend: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback_return: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("search_runs.id"), nullable=False)


class AgendaShare(Base):
    __tablename__ = "agenda_shares"
    __table_args__ = (
        UniqueConstraint(
            "agenda_item_id",
            "sender_user_id",
            "recipient_user_id",
            name="uq_agenda_share_unique_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agenda_item_id: Mapped[int] = mapped_column(ForeignKey("agenda_items.id"), nullable=False, index=True)
    sender_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_seen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now_rome, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class UserSetting(Base):
    __tablename__ = "user_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_settings_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
