"""explicit "unavailable" days of an availability submission

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-17

Until now a day without shifts was ambiguous: the employee had either chosen "לא זמין/ה" or never touched it. From now on
every one of the seven days needs an explicit choice (at least one shift, or "לא זמין/ה"), and the explicit "unavailable" days are
stored here. Additive only: submissions saved before this change keep their slots and simply have no rows here; the application
never assumes that their empty days were unavailable (the employee is asked to choose when editing). Downgrading drops the table.
"""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "availability_unavailable_days",
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["availability_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("submission_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("availability_unavailable_days")
