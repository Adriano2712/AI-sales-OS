"""messages.language

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("language", sa.String(10), nullable=False, server_default="pt-BR"),
    )


def downgrade() -> None:
    op.drop_column("messages", "language")
