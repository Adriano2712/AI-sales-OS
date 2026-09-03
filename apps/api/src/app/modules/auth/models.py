import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, UUIDPkMixin


class User(Base, UUIDPkMixin, TimestampMixin):
    """Mirrors auth.users from Supabase Auth. Not tenant-scoped — a user can belong
    to multiple tenants via Membership."""

    __tablename__ = "users"

    auth_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
