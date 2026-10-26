"""Username policy shared by forms, provisioning and model writes."""
from sqlalchemy import event, inspect, select
from sqlalchemy.exc import IntegrityError


def identity_key(value, handle=False):
    value = str(value or '').strip()
    if handle:
        value = value.lstrip('@')
    return value.casefold() or None


def unique_identity_field(form, field):
    from .models import User
    from wtforms.validators import ValidationError
    key = identity_key(field.data, handle=field.name != 'username')
    if key is None:
        return
    query = User.query.filter(getattr(User, field.name + '_key') == key)
    owner_id = getattr(form, 'identity_user_id', None)
    if owner_id is not None:
        from . import db
        owner = db.session.get(User, owner_id)
        if owner and identity_key(getattr(owner, field.name), handle=field.name != 'username') == key:
            return  # Grandfather existing duplicates when their owner keeps them.
        query = query.filter(User.id != owner_id)
    if query.first() is not None:
        raise ValidationError(f'{field.label.text.replace(" (optional)", "")} is already in use.')


def check_username(value):
    if any(char.isspace() for char in (value or '')):
        raise ValueError('Usernames cannot contain spaces or other whitespace, including at the beginning or end.')


def username_field(form, field):
    unique_identity_field(form, field)
    # Existing names remain usable; changing a name must satisfy the new policy.
    if field.object_data is None or field.data != field.object_data:
        from wtforms.validators import ValidationError
        try:
            check_username(field.data)
        except ValueError as error:
            raise ValidationError(str(error))


def install_username_policy(model):
    def set_identity_keys(connection, target, inserting=False):
        for name in ('username', 'tg_username', 'discord_username'):
            if not inserting and not inspect(target).attrs[name].history.has_changes():
                continue
            key = identity_key(getattr(target, name), handle=name != 'username')
            if not inserting and key == getattr(target, name + '_key'):
                continue
            if key is not None:
                query = select(model.id).where(getattr(model, name + '_key') == key)
                if not inserting:
                    query = query.where(model.id != target.id)
                if connection.execute(query.limit(1)).first() is not None:
                    raise IntegrityError(None, None, ValueError(f'{name} is already in use.'))
            setattr(target, name + '_key', key)

    @event.listens_for(model, 'before_insert')
    def inserting(mapper, connection, target):
        check_username(target.username)
        target.identity_uniqueness_scope = 0
        set_identity_keys(connection, target, inserting=True)

    @event.listens_for(model, 'before_update')
    def updating(mapper, connection, target):
        if inspect(target).attrs.username.history.has_changes():
            check_username(target.username)
        set_identity_keys(connection, target)
