"""Username policy shared by forms, provisioning and model writes."""
from sqlalchemy import event, inspect


def check_username(value):
    if any(char.isspace() for char in (value or '')):
        raise ValueError('Usernames cannot contain spaces or other whitespace, including at the beginning or end.')


def username_field(form, field):
    # Existing names remain usable; changing a name must satisfy the new policy.
    if field.object_data is None or field.data != field.object_data:
        from wtforms.validators import ValidationError
        try:
            check_username(field.data)
        except ValueError as error:
            raise ValidationError(str(error))


def install_username_policy(model):
    @event.listens_for(model, 'before_insert')
    def inserting(mapper, connection, target):
        check_username(target.username)

    @event.listens_for(model, 'before_update')
    def updating(mapper, connection, target):
        if inspect(target).attrs.username.history.has_changes():
            check_username(target.username)
