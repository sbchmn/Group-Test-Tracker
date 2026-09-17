"""Add control plane nonce and operation receipt tables.

Revision ID: f2b6c9a1d4e7
Revises: e9c2a7d4b6f1
Create Date: 2026-09-15 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2b6c9a1d4e7'
down_revision = 'e9c2a7d4b6f1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'control_plane_nonces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nonce_digest', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nonce_digest'),
    )
    with op.batch_alter_table('control_plane_nonces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_control_plane_nonces_nonce_digest'), ['nonce_digest'], unique=True)
        batch_op.create_index(batch_op.f('ix_control_plane_nonces_expires_at'), ['expires_at'], unique=False)

    op.create_table(
        'control_plane_operation_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('operation_id', sa.String(length=160), nullable=False),
        sa.Column('payload_digest', sa.String(length=64), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operation_id'),
    )
    with op.batch_alter_table('control_plane_operation_receipts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_control_plane_operation_receipts_operation_id'), ['operation_id'], unique=True)


def downgrade():
    with op.batch_alter_table('control_plane_operation_receipts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_control_plane_operation_receipts_operation_id'))
    op.drop_table('control_plane_operation_receipts')

    with op.batch_alter_table('control_plane_nonces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_control_plane_nonces_expires_at'))
        batch_op.drop_index(batch_op.f('ix_control_plane_nonces_nonce_digest'))
    op.drop_table('control_plane_nonces')
