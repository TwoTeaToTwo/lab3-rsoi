"""Initial Ticket schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_ticket"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_uid", sa.Uuid(), nullable=False, unique=True),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("flight_number", sa.String(20), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_ticket_price"),
        sa.CheckConstraint("status IN ('PAID','CANCELED')", name="ck_ticket_status"),
    )
    op.create_index("ix_ticket_username_id", "ticket", ["username", "id"])


def downgrade() -> None:
    op.drop_table("ticket")
