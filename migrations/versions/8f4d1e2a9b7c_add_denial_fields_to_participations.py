"""Add denied state fields to participations

Revision ID: 8f4d1e2a9b7c
Revises: 7c1a2b3d4e5f
Create Date: 2026-08-20 12:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8f4d1e2a9b7c'
down_revision = '7c1a2b3d4e5f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('denied', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('denied_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('denied_reason', sa.Text(), nullable=True))
        batch_op.create_index(batch_op.f('ix_participations_denied'), ['denied'], unique=False)


def downgrade():
    with op.batch_alter_table('participations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_participations_denied'))
        batch_op.drop_column('denied_reason')
        batch_op.drop_column('denied_at')
        batch_op.drop_column('denied')
