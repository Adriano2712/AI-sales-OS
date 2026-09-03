import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    # Without this, a column with server_default/onupdate (e.g. TimestampMixin's
    # updated_at) is left "expired" after flush — SQLAlchemy would normally
    # refresh it with a lazy-load on next access, but under the async engine
    # that requires an explicit await. Serializing the object right after a
    # mutation (our common create/update -> return Read.model_validate(obj)
    # pattern) accesses it synchronously and blows up with MissingGreenlet.
    # eager_defaults makes flush fetch these via RETURNING instead, so the
    # attribute is already populated — inherited by every mapped subclass.
    __mapper_args__ = {"eager_defaults": True}


class UUIDPkMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantScopedMixin:
    """Mixin for tables isolated by RLS on tenant_id. See database/migrations RLS policies."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Sets the Postgres session variable the tenant-scoped RLS policies key off of.

    Must run inside the same transaction as the queries it protects — SET LOCAL is
    transaction-scoped, so this needs to be called after a transaction has started
    and before any tenant-scoped query in that same session/transaction.
    """
    await session.execute(
        text("SELECT set_config('request.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def set_user_context(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Sets the session variable the `memberships` RLS policy keys off of.

    Needed one step earlier than set_tenant_context: memberships is what the app
    queries *to determine* the tenant, so it can't be gated on request.tenant_id
    without a chicken-and-egg problem. It's gated on the resolved local user id
    instead.
    """
    await session.execute(
        text("SELECT set_config('request.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
