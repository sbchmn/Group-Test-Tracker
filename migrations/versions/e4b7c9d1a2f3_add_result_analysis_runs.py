"""Add durable automated result analysis runs and findings."""

from alembic import op
import sqlalchemy as sa


revision = 'e4b7c9d1a2f3'
down_revision = 'b2c4d6e8f0a1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'result_analysis_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_test_id', sa.Integer(), nullable=True),
        sa.Column('public_result_id', sa.Integer(), nullable=True),
        sa.Column('source_kind', sa.String(length=20), nullable=False),
        sa.Column('source_reference', sa.String(length=500), nullable=False),
        sa.Column('source_sha256', sa.String(length=64), nullable=True),
        sa.Column('source_content_type', sa.String(length=100), nullable=True),
        sa.Column('source_size_bytes', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('provider_model', sa.String(length=120), nullable=False),
        sa.Column('schema_version', sa.String(length=20), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=30), nullable=False, server_default='queued'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('next_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('lease_token', sa.String(length=64), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
        sa.Column('error_code', sa.String(length=60), nullable=True),
        sa.Column('error_message', sa.String(length=500), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('usage_json', sa.JSON(), nullable=True),
        sa.Column('requested_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('queued_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            '(group_test_id IS NOT NULL AND public_result_id IS NULL) OR '
            '(group_test_id IS NULL AND public_result_id IS NOT NULL)',
            name='ck_result_analysis_exactly_one_target',
        ),
        sa.CheckConstraint("source_kind IN ('upload', 'link')", name='ck_result_analysis_source_kind'),
        sa.CheckConstraint(
            "status IN ('queued', 'analyzing', 'needs_review', 'applied', 'failed', 'superseded')",
            name='ck_result_analysis_status',
        ),
        sa.CheckConstraint("provider IN ('openai', 'xai', 'anthropic')", name='ck_result_analysis_provider'),
        sa.ForeignKeyConstraint(['group_test_id'], ['group_tests.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['public_result_id'], ['public_results.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in ('group_test_id', 'public_result_id', 'source_sha256', 'status', 'next_attempt_at', 'lease_token', 'lease_expires_at', 'queued_at'):
        op.create_index(f'ix_result_analysis_runs_{column}', 'result_analysis_runs', [column], unique=False)
    op.create_index('ix_result_analysis_status_queue', 'result_analysis_runs', ['status', 'next_attempt_at', 'queued_at'], unique=False)

    op.create_table(
        'result_analysis_findings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analysis_run_id', sa.Integer(), nullable=False),
        sa.Column('canonical_type', sa.String(length=80), nullable=True),
        sa.Column('source_label', sa.String(length=200), nullable=False),
        sa.Column('reported_value', sa.String(length=500), nullable=False),
        sa.Column('evidence_text', sa.String(length=1000), nullable=False),
        sa.Column('page_number', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('is_reported_aggregate', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('proposed_action', sa.String(length=20), nullable=False),
        sa.Column('target_row_key', sa.String(length=120), nullable=True),
        sa.Column('review_decision', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('reviewed_value', sa.String(length=500), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "proposed_action IN ('fill', 'create', 'conflict', 'unrecognized')",
            name='ck_result_analysis_finding_action',
        ),
        sa.CheckConstraint(
            "review_decision IN ('pending', 'accepted', 'rejected')",
            name='ck_result_analysis_finding_review',
        ),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_result_analysis_confidence'),
        sa.ForeignKeyConstraint(['analysis_run_id'], ['result_analysis_runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_result_analysis_findings_analysis_run_id', 'result_analysis_findings', ['analysis_run_id'], unique=False)
    op.create_index('ix_result_analysis_findings_canonical_type', 'result_analysis_findings', ['canonical_type'], unique=False)


def downgrade():
    op.drop_index('ix_result_analysis_findings_canonical_type', table_name='result_analysis_findings')
    op.drop_index('ix_result_analysis_findings_analysis_run_id', table_name='result_analysis_findings')
    op.drop_table('result_analysis_findings')
    op.drop_index('ix_result_analysis_status_queue', table_name='result_analysis_runs')
    for column in reversed(('group_test_id', 'public_result_id', 'source_sha256', 'status', 'next_attempt_at', 'lease_token', 'lease_expires_at', 'queued_at')):
        op.drop_index(f'ix_result_analysis_runs_{column}', table_name='result_analysis_runs')
    op.drop_table('result_analysis_runs')
