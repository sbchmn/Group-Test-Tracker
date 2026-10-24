"""Preserve account merge decisions and distinguish archived payment history."""
from alembic import op
import sqlalchemy as sa

revision = 'b4d6f8a0c2e3'
down_revision = 'a9c3e5f7b2d4'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('users', recreate='always', table_kwargs={'sqlite_autoincrement': True}):
            pass
    op.create_table('account_merge_audits',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('performed_by_id', sa.Integer(), nullable=False),
        sa.Column('primary_user_id', sa.Integer(), nullable=False),
        sa.Column('duplicate_user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False))
    with op.batch_alter_table('payment_submissions') as batch:
        batch.add_column(sa.Column('archived_by_merge', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table('payment_submissions') as batch:
        batch.drop_column('archived_by_merge')
    op.drop_table('account_merge_audits')
