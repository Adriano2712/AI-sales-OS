import uuid

from pydantic import BaseModel


class AuthenticatedUser(BaseModel):
    auth_user_id: uuid.UUID
    email: str
