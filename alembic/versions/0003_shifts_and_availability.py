"""shifts and availability: shift definitions with staffing, weekly submissions and their slots

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12

Additive only. Shift times are wall-clock times in Asia/Jerusalem; end_time <= start_time means the shift
ends on the next calendar day (for example 16:00-00:00). The seed command, not this migration, inserts the
demo shifts, so existing environments keep whatever shift settings they already have.
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('shifts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('required_staff', sa.Integer(), nullable=False),
    sa.CheckConstraint('required_staff >= 0', name='ck_shifts_required_staff'),
    sa.CheckConstraint('start_time <> end_time', name='ck_shifts_times_differ'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('availability_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('week_start', sa.Date(), nullable=False),
    sa.Column('pref_min', sa.Integer(), nullable=True),
    sa.Column('pref_max', sa.Integer(), nullable=True),
    sa.Column('free_text', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('free_text IS NULL OR length(free_text) <= 1000', name='ck_submission_free_text_len'),
    sa.CheckConstraint('pref_max IS NULL OR pref_max >= 0', name='ck_submission_pref_max'),
    sa.CheckConstraint('pref_min IS NULL OR pref_max IS NULL OR pref_min <= pref_max', name='ck_submission_pref_order'),
    sa.CheckConstraint('pref_min IS NULL OR pref_min >= 0', name='ck_submission_pref_min'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'week_start', name='uq_submission_user_week')
    )
    with op.batch_alter_table('availability_submissions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_availability_submissions_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_availability_submissions_week_start'), ['week_start'], unique=False)

    op.create_table('availability_slots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('submission_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('shift_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['shift_id'], ['shifts.id'], ),
    sa.ForeignKeyConstraint(['submission_id'], ['availability_submissions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('submission_id', 'day', 'shift_id', name='uq_slot_submission_day_shift')
    )
    with op.batch_alter_table('availability_slots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_availability_slots_shift_id'), ['shift_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_availability_slots_submission_id'), ['submission_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('availability_slots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_availability_slots_submission_id'))
        batch_op.drop_index(batch_op.f('ix_availability_slots_shift_id'))

    op.drop_table('availability_slots')
    with op.batch_alter_table('availability_submissions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_availability_submissions_week_start'))
        batch_op.drop_index(batch_op.f('ix_availability_submissions_user_id'))

    op.drop_table('availability_submissions')
    op.drop_table('shifts')
