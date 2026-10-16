"""Flight schema and laboratory seed data."""

from datetime import datetime
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision = "0001_flight"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    airport = op.create_table(
        "airport",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("city", sa.String(255), nullable=False),
        sa.Column("country", sa.String(255), nullable=False),
    )
    flight = op.create_table(
        "flight",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flight_number", sa.String(20), nullable=False, unique=True),
        sa.Column("datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_airport_id", sa.Integer(), sa.ForeignKey("airport.id"), nullable=False),
        sa.Column("to_airport_id", sa.Integer(), sa.ForeignKey("airport.id"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_flight_price"),
    )
    op.bulk_insert(
        airport,
        [
            {"id": 1, "name": "Шереметьево", "city": "Москва", "country": "Россия"},
            {"id": 2, "name": "Пулково", "city": "Санкт-Петербург", "country": "Россия"},
        ],
    )
    op.bulk_insert(
        flight,
        [
            {
                "id": 1,
                "flight_number": "AFL031",
                "datetime": datetime(2021, 10, 8, 20, 0, tzinfo=ZoneInfo("Europe/Moscow")),
                "from_airport_id": 2,
                "to_airport_id": 1,
                "price": 1500,
            }
        ],
    )
    op.execute("SELECT setval(pg_get_serial_sequence('airport', 'id'), 2)")
    op.execute("SELECT setval(pg_get_serial_sequence('flight', 'id'), 1)")


def downgrade() -> None:
    op.drop_table("flight")
    op.drop_table("airport")
