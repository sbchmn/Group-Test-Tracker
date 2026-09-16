"""Add support credential state and expiry metadata.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-16 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('support_state', sa.String(length=20), nullable=False, server_default='disabled'))
        batch_op.add_column(sa.Column('support_credential_version', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('support_expires_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('support_expires_at')
        batch_op.drop_column('support_credential_version')
        batch_op.drop_column('support_state')
