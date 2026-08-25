"""Add object storage image keys for results.

Revision ID: c3d9e1f4a7b2
Revises: 8f4d1e2a9b7c
Create Date: 2026-08-25 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d9e1f4a7b2'
down_revision = '8f4d1e2a9b7c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('results_image_key', sa.String(length=500), nullable=True))

    with op.batch_alter_table('public_results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('results_image_key', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('public_results', schema=None) as batch_op:
        batch_op.drop_column('results_image_key')

    with op.batch_alter_table('group_tests', schema=None) as batch_op:
        batch_op.drop_column('results_image_key')
