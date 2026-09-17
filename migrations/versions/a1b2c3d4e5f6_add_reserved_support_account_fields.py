"""Add reserved support-account marker and session epoch to users.

Revision ID: a1b2c3d4e5f6
Revises: f2b6c9a1d4e7
Create Date: 2026-09-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f2b6c9a1d4e7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('system_account_key', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('session_epoch', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_index(batch_op.f('ix_users_system_account_key'), ['system_account_key'], unique=True)

    # Identify the reserved support identity without guessing from an existing
    # username: only a normalized gtmsupport/support@grouptest.online match that
    # is already an inert (is_active=False) admin account is safely adopted here.
    # Any other conflicting account is left untouched for manual resolution.
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE users SET system_account_key = 'control_plane_support' "
        "WHERE lower(username) = 'gtmsupport' AND lower(email) = 'support@grouptest.online' "
        "AND is_admin = 1 AND is_active = 0"
    ))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_system_account_key'))
        batch_op.drop_column('session_epoch')
        batch_op.drop_column('system_account_key')
