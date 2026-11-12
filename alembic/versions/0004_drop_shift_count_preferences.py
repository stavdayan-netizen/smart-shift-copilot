"""drop the min/max shift-count preference columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12

The owner removed numeric shift-count preferences (2026-11-12): availability keeps only an optional
free-text preference (at most 1,000 characters, still enforced by ck_submission_free_text_len).
Upgrading discards any values in pref_min and pref_max (the columns were never written by the application:
the availability form arrives in the same release). Downgrading adds the columns back, empty and nullable,
with their original checks.
"""
from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("availability_submissions", schema=None) as batch_op:
        batch_op.drop_constraint("ck_submission_pref_order", type_="check")
        batch_op.drop_constraint("ck_submission_pref_max", type_="check")
        batch_op.drop_constraint("ck_submission_pref_min", type_="check")
        batch_op.drop_column("pref_max")
        batch_op.drop_column("pref_min")


def downgrade() -> None:
    with op.batch_alter_table("availability_submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pref_min", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pref_max", sa.Integer(), nullable=True))
        batch_op.create_check_constraint("ck_submission_pref_min", "pref_min IS NULL OR pref_min >= 0")
        batch_op.create_check_constraint("ck_submission_pref_max", "pref_max IS NULL OR pref_max >= 0")
        batch_op.create_check_constraint("ck_submission_pref_order", "pref_min IS NULL OR pref_max IS NULL OR pref_min <= pref_max")
