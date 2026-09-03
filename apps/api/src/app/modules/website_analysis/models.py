import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPkMixin
from app.modules.website_analysis.enums import PageType


class Website(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "websites"
    __table_args__ = (UniqueConstraint("tenant_id", "company_id", name="uq_website_company"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))


class WebsitePage(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """Replaced wholesale on every analysis run — a fresh snapshot, not an
    accumulating history. WebsiteAnalysis is the historical record."""

    __tablename__ = "website_pages"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    page_type: Mapped[PageType] = mapped_column(Enum(PageType, name="website_page_type"))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    has_viewport_meta: Mapped[bool] = mapped_column(Boolean, default=False)
    has_contact_form: Mapped[bool] = mapped_column(Boolean, default=False)
    has_phone_link: Mapped[bool] = mapped_column(Boolean, default=False)
    has_email_link: Mapped[bool] = mapped_column(Boolean, default=False)
    has_whatsapp_link: Mapped[bool] = mapped_column(Boolean, default=False)
    has_nav: Mapped[bool] = mapped_column(Boolean, default=False)
    has_custom_stylesheet: Mapped[bool] = mapped_column(Boolean, default=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WebsiteAnalysis(Base, UUIDPkMixin, TenantScopedMixin, TimestampMixin):
    """Append-only — one row per analysis run, so a score's history over
    time is visible rather than only the latest snapshot."""

    __tablename__ = "website_analyses"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), index=True
    )
    digital_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_funcionamento: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_mobile: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_ux: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_conversao: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_conteudo: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_design: Mapped[float | None] = mapped_column(Float, nullable=True)
    findings: Mapped[dict] = mapped_column(JSON, default=dict)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
