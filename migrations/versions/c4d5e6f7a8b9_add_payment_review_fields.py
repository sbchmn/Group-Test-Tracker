"""Add participant payment claim/verification fields and the payment review template flag.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4d5e6f7a8b9'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_claimed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('payment_verified_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('payment_verified_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_participations_payment_verified_by_users',
            'users', ['payment_verified_by_id'], ['id'],
        )

    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_default_payment_review', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('notification_templates', schema=None) as batch_op:
        batch_op.drop_column('is_default_payment_review')

    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_participations_payment_verified_by_users', type_='foreignkey')
        batch_op.drop_column('payment_verified_by_id')
        batch_op.drop_column('payment_verified_at')
        batch_op.drop_column('payment_claimed_at')
