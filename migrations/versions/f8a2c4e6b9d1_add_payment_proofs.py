"""Add payment proof policies and versioned payment submissions."""
from alembic import op
import sqlalchemy as sa

revision = 'f8a2c4e6b9d1'
down_revision = 'd9f3a6c8e2b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payment_options') as batch:
        batch.add_column(sa.Column('proof_image_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('proof_transaction_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('proof_requirement', sa.String(12), nullable=False, server_default='optional'))
    with op.batch_alter_table('participations') as batch:
        batch.add_column(sa.Column('payment_revision', sa.Integer(), nullable=False, server_default='0'))
    op.create_table(
        'payment_submissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('participation_id', sa.Integer(), sa.ForeignKey('participations.id'), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('method_snapshot', sa.JSON(), nullable=False),
        sa.Column('transaction_id', sa.String(255)),
        sa.Column('image_key', sa.String(500)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime()),
        sa.Column('reviewed_by_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('denial_reason', sa.String(1000)),
    )
    op.create_index('ix_payment_submissions_participation_id', 'payment_submissions', ['participation_id'])


def downgrade():
    op.drop_table('payment_submissions')
    with op.batch_alter_table('participations') as batch:
        batch.drop_column('payment_revision')
    with op.batch_alter_table('payment_options') as batch:
        batch.drop_column('proof_requirement')
        batch.drop_column('proof_transaction_enabled')
        batch.drop_column('proof_image_enabled')
