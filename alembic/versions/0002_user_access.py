"""user access roles, code hash, login throttle

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-11

Additive only (safe to roll the app back one release): existing users become employees with no
code, so they cannot log in until an operator issues a code.
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('login_throttle',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    with op.batch_alter_table('login_throttle', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_throttle_updated_at'), ['updated_at'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('access_role', sa.String(length=10), server_default=sa.text("'employee'"), nullable=False))
        batch_op.add_column(sa.Column('code_hash', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False))
        batch_op.create_check_constraint('ck_users_access_role', "access_role in ('employee', 'manager')")



def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('ck_users_access_role', type_='check')
        batch_op.drop_column('token_version')
        batch_op.drop_column('code_hash')
        batch_op.drop_column('access_role')

    with op.batch_alter_table('login_throttle', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_login_throttle_updated_at'))

    op.drop_table('login_throttle')
