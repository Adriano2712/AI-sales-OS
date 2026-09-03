"""One-off script: creates a dev tenant and makes an existing Supabase Auth user
its ADMIN.

There's no "create tenant" / "invite user" endpoint yet (that's product work
for a later phase) — this exists purely to unblock local development, since
/api/v1/auth/me returns 403 until the logged-in user has at least one
membership.

Usage:
    1. Sign up once through the web app's /login page (or the Supabase
       dashboard) so a Supabase Auth user exists.
    2. Find that user's UUID: Supabase dashboard -> Authentication -> Users.
    3. Run, with MIGRATIONS_DATABASE_URL set (this needs the admin role —
       inserting a membership is denied by RLS for the app role by design,
       see docs/DATABASE.md):

       MIGRATIONS_DATABASE_URL=... python database/seeds/seed_dev_tenant.py \\
           --auth-user-id <uuid> --email you@example.com --tenant-name "Dev Tenant"
"""

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.modules.auth.models import User  # noqa: E402
from app.modules.tenancy.enums import Role  # noqa: E402
from app.modules.tenancy.models import Membership, Tenant  # noqa: E402


async def main(auth_user_id: uuid.UUID, email: str, tenant_name: str) -> None:
    database_url = os.environ.get("MIGRATIONS_DATABASE_URL")
    if not database_url:
        raise SystemExit("MIGRATIONS_DATABASE_URL must be set (admin role — see module docstring)")

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_factory() as db:  # type: AsyncSession
        result = await db.execute(select(User).where(User.auth_user_id == auth_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(auth_user_id=auth_user_id, email=email)
            db.add(user)
            await db.flush()

        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        await db.flush()

        db.add(Membership(user_id=user.id, tenant_id=tenant.id, role=Role.ADMIN))
        await db.commit()

        print(f"Created tenant {tenant.id} ({tenant_name!r}) with {email} as ADMIN")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-user-id", type=uuid.UUID, required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--tenant-name", default="Dev Tenant")
    args = parser.parse_args()

    asyncio.run(main(args.auth_user_id, args.email, args.tenant_name))
