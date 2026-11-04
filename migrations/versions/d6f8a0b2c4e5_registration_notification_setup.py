"""Add registration setup and grandfather existing duplicate identities."""
from alembic import op
import sqlalchemy as sa

revision = 'd6f8a0b2c4e5'
down_revision = 'c5e7a9b1d3f4'
branch_labels = None
depends_on = None


def _key(value, handle=False):
    value = str(value or '').strip()
    return (value.lstrip('@') if handle else value).casefold() or None


def upgrade():
    connection = op.get_bind()
    sequence = _sqlite_sequence(connection)
    rows = connection.execute(sa.text('SELECT id, username, tg_username, discord_username FROM users')).mappings().all()
    fields = ('username', 'tg_username', 'discord_username')
    values = []
    for row in rows:
        entry = {'id': row['id']}
        for field in fields:
            key = _key(row[field], handle=field != 'username')
            entry[field + '_key'] = key
        values.append(entry)
    with op.batch_alter_table('users') as batch:
        for field in fields:
            batch.add_column(sa.Column(field + '_key', sa.String(240), nullable=True))
        batch.add_column(sa.Column('pending_notification_channel', sa.String(20), nullable=True))
        batch.add_column(sa.Column('notification_setup_expires_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('identity_uniqueness_scope', sa.Integer(), nullable=False, server_default='0'))
    if values:
        connection.execute(sa.text('UPDATE users SET username_key=:username_key, tg_username_key=:tg_username_key, discord_username_key=:discord_username_key, identity_uniqueness_scope=id WHERE id=:id'), values)
    with op.batch_alter_table('users', table_kwargs={'sqlite_autoincrement': True}) as batch:
        batch.alter_column('username_key', existing_type=sa.String(240), nullable=False)
        for field in fields:
            batch.create_unique_constraint('uq_users_' + field + '_key', [field + '_key', 'identity_uniqueness_scope'])
            batch.create_index('ix_users_' + field + '_key', [field + '_key'])
    _restore_sequence(connection, sequence)


def downgrade():
    connection = op.get_bind()
    sequence = _sqlite_sequence(connection)
    with op.batch_alter_table('users', table_kwargs={'sqlite_autoincrement': True}) as batch:
        for field in ('username', 'tg_username', 'discord_username'):
            batch.drop_constraint('uq_users_' + field + '_key', type_='unique')
            batch.drop_index('ix_users_' + field + '_key')
            batch.drop_column(field + '_key')
        batch.drop_column('pending_notification_channel')
        batch.drop_column('notification_setup_expires_at')
        batch.drop_column('identity_uniqueness_scope')
    _restore_sequence(connection, sequence)


def _sqlite_sequence(connection):
    if connection.dialect.name == 'sqlite':
        return connection.execute(sa.text("SELECT seq FROM sqlite_sequence WHERE name='users'")).scalar() or 0
    return 0


def _restore_sequence(connection, sequence):
    if connection.dialect.name == 'sqlite':
        result = connection.execute(sa.text("UPDATE sqlite_sequence SET seq=MAX(seq, :sequence) WHERE name='users'"), {'sequence': sequence})
        if not result.rowcount and sequence:
            connection.execute(sa.text("INSERT INTO sqlite_sequence (name, seq) VALUES ('users', :sequence)"), {'sequence': sequence})
