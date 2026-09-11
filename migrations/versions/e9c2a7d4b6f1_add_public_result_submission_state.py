"""Add draft and Telegram review state to public results."""

from alembic import op
import sqlalchemy as sa


revision = 'e9c2a7d4b6f1'
down_revision = 'd8a4f2c6b9e1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('public_results') as batch:
        batch.alter_column('results_link', existing_type=sa.String(length=500), nullable=True)
        batch.add_column(sa.Column('publication_status', sa.String(length=20), nullable=False, server_default='published'))
        batch.add_column(sa.Column('submission_platform', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('submission_chat_id', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('submission_thread_id', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('submission_message_id', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('review_message_id', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('review_state_json', sa.JSON(), nullable=True))
    op.create_index('ix_public_results_publication_status', 'public_results', ['publication_status'], unique=False)


def downgrade():
    op.drop_index('ix_public_results_publication_status', table_name='public_results')
    with op.batch_alter_table('public_results') as batch:
        for name in ('review_state_json', 'review_message_id', 'submission_message_id', 'submission_thread_id', 'submission_chat_id', 'submission_platform', 'publication_status'):
            batch.drop_column(name)
        batch.alter_column('results_link', existing_type=sa.String(length=500), nullable=False)
