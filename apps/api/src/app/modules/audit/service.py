import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.enums import AuditEventType
from app.modules.audit.models import AuditLog


async def log_event(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    event_type: AuditEventType,
    payload: dict | None = None,
) -> AuditLog:
    entry = AuditLog(tenant_id=tenant_id, event_type=event_type.value, payload=payload or {})
    db.add(entry)
    await db.flush()
    return entry
