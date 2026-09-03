from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.auth.schemas import AuthenticatedUser


async def get_or_create_user(db: AsyncSession, authenticated: AuthenticatedUser) -> User:
    """Provisions the local `users` row on first sight of a Supabase-authenticated
    identity. Supabase Auth remains the source of truth for credentials; this table
    only exists so other tables can FK to a stable local id."""
    result = await db.execute(select(User).where(User.auth_user_id == authenticated.auth_user_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(auth_user_id=authenticated.auth_user_id, email=authenticated.email)
    db.add(user)
    await db.flush()
    return user
