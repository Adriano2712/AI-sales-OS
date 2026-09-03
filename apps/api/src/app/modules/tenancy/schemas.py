import uuid

from pydantic import BaseModel

from app.modules.tenancy.enums import Role


class TenantContext(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: Role
