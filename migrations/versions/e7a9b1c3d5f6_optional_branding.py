"""Add optional branding, immutable assets, revisions, and member themes."""
from alembic import op
import sqlalchemy as sa

revision = 'e7a9b1c3d5f6'
down_revision = 'd6f8a0b2c4e5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('theme_preference', sa.String(10), nullable=False, server_default='site'))
    op.create_table('branding_state',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('draft', sa.JSON(), nullable=False),
        sa.Column('published', sa.JSON(), nullable=False))
    op.create_table('branding_revisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('settings', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('branding_assets',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('data', sa.LargeBinary(length=4194304), nullable=False),
        sa.Column('icon_data', sa.LargeBinary(length=4194304), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('published', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('branding_assets')
    op.drop_table('branding_revisions')
    op.drop_table('branding_state')
    connection = op.get_bind()
    sequence = connection.execute(sa.text("SELECT seq FROM sqlite_sequence WHERE name='users'")).scalar() if connection.dialect.name == 'sqlite' else None
    with op.batch_alter_table('users', table_kwargs={'sqlite_autoincrement': True}) as batch:
        batch.drop_column('theme_preference')
    if sequence is not None:
        result = connection.execute(sa.text("UPDATE sqlite_sequence SET seq=MAX(seq, :seq) WHERE name='users'"), {'seq': sequence})
        if not result.rowcount:
            connection.execute(sa.text("INSERT INTO sqlite_sequence(name,seq) VALUES ('users', :seq)"), {'seq': sequence})
