"""Initial Bonus schema and durable operation results."""

import sqlalchemy as sa
from alembic import op

revision = "0001_bonus"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "privilege",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("status", sa.String(80), nullable=False, server_default="BRONZE"),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("balance >= 0", name="ck_privilege_balance"),
        sa.CheckConstraint("status IN ('BRONZE','SILVER','GOLD')", name="ck_privilege_status"),
    )
    op.create_table(
        "privilege_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("privilege_id", sa.Integer(), sa.ForeignKey("privilege.id"), nullable=False),
        sa.Column("ticket_uid", sa.Uuid(), nullable=False),
        sa.Column("datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balance_diff", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(20), nullable=False),
        sa.CheckConstraint("balance_diff >= 0", name="ck_history_amount"),
        sa.CheckConstraint(
            "operation_type IN ('FILL_IN_BALANCE','DEBIT_THE_ACCOUNT')", name="ck_history_type"
        ),
    )
    op.create_index("ix_privilege_history_privilege_id", "privilege_history", ["privilege_id"])
    op.create_table(
        "bonus_operation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_uid", sa.Uuid(), nullable=False),
        sa.Column("privilege_id", sa.Integer(), sa.ForeignKey("privilege.id"), nullable=False),
        sa.Column("paid_from_balance", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("paid_by_money", sa.Integer(), nullable=False),
        sa.Column("paid_by_bonuses", sa.Integer(), nullable=False),
        sa.Column("accrued", sa.Integer(), nullable=False),
        sa.Column("result_balance", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(80), nullable=False),
        sa.Column("reversed", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("ticket_uid", name="uq_bonus_operation_ticket_uid"),
        sa.CheckConstraint(
            "price >= 0 AND paid_by_money >= 0 AND paid_by_bonuses >= 0 "
            "AND accrued >= 0 AND result_balance >= 0",
            name="ck_operation_amounts",
        ),
        sa.CheckConstraint("paid_by_money + paid_by_bonuses = price", name="ck_operation_payment"),
        sa.CheckConstraint(
            "result_status IN ('BRONZE','SILVER','GOLD')", name="ck_operation_status"
        ),
    )
    op.create_index("ix_bonus_operation_privilege_id", "bonus_operation", ["privilege_id"])


def downgrade() -> None:
    op.drop_table("bonus_operation")
    op.drop_table("privilege_history")
    op.drop_table("privilege")
