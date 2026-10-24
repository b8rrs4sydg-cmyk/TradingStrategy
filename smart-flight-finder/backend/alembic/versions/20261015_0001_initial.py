"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-15

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("country", sa.String(2), nullable=False, index=True),
        sa.Column("day", sa.Date, nullable=False, index=True),
        sa.Column("name_zh", sa.String(64), nullable=False),
        sa.Column("name_en", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("is_workday", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.String(255)),
        sa.UniqueConstraint("country", "day", name="uq_holiday_country_day"),
    )

    op.create_table(
        "leave_strategies",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("year", sa.Integer, nullable=False, index=True),
        sa.Column("holiday_key", sa.String(32), nullable=False, index=True),
        sa.Column("label_zh", sa.String(64), nullable=False),
        sa.Column("pto_days", sa.Integer, nullable=False),
        sa.Column("total_days", sa.Integer, nullable=False),
        sa.Column("window_start", sa.Date, nullable=False),
        sa.Column("window_end", sa.Date, nullable=False),
        sa.Column("description", sa.String(255)),
        sa.Column(
            "anchor_holiday_id",
            sa.Integer,
            sa.ForeignKey("holidays.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "itinerary_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), index=True),
        sa.Column("trip_type", sa.String(16), nullable=False),
        sa.Column("cabin", sa.String(24), nullable=False, server_default="economy"),
        sa.Column("adults", sa.Integer, nullable=False, server_default="1"),
        sa.Column("children", sa.Integer, nullable=False, server_default="0"),
        sa.Column("infants", sa.Integer, nullable=False, server_default="0"),
        sa.Column("origins", sa.JSON, nullable=False),
        sa.Column("destinations", sa.JSON, nullable=False),
        sa.Column("strategies", sa.JSON, nullable=False),
        sa.Column("holiday_key", sa.String(32), index=True),
        sa.Column("max_total_budget", sa.Integer),
        sa.Column("max_pto_days", sa.Integer),
        sa.Column("scoring_weights", sa.JSON),
    )

    op.create_table(
        "date_windows",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "request_id",
            sa.Integer,
            sa.ForeignKey("itinerary_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("anchor_date", sa.Date, nullable=False),
        sa.Column("flex_before", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flex_after", sa.Integer, nullable=False, server_default="0"),
        sa.Column("allow_weekend_only", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("segment_origin", sa.String(8)),
        sa.Column("segment_destination", sa.String(8)),
    )


def downgrade() -> None:
    op.drop_table("date_windows")
    op.drop_table("itinerary_requests")
    op.drop_table("leave_strategies")
    op.drop_table("holidays")
