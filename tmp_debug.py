from unittest.mock import Mock, patch
from app import create_app, db
from app.models import NotificationConfig, User
from app.notifications import send_mailjet_message, _get_config, _get_user_attr
app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
app.config['WTF_CSRF_ENABLED'] = False
with app.app_context():
    db.create_all()
    user = User(username='mailer', email='mailer@example.com')
    user.set_password('secret')
    db.session.add(user)
    db.session.add_all([
        NotificationConfig(key='mailjet_api_key', value='api-key'),
        NotificationConfig(key='mailjet_secret_key', value='secret-key'),
        NotificationConfig(key='mailjet_sender_email', value='sender@example.com'),
    ])
    db.session.commit()
    user = db.session.merge(user)
    print('config', _get_config('mailjet_api_key'), _get_config('mailjet_secret_key'), _get_config('mailjet_sender_email'))
    print('user attrs', _get_user_attr(user,'email',None), _get_user_attr(user,'username',None))
    with patch('app.notifications.urlopen') as mock_urlopen:
        response = Mock()
        response.read.return_value = b'{"message":"success"}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = response
        result = send_mailjet_message(user, 'Hello', 'Body')
        print('result', result)
        print('called', mock_urlopen.called)
        print('call args', mock_urlopen.call_args)
