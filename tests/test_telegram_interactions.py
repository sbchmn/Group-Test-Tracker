import io
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app, db
from app.models import NotificationConfig, PublicResult, TelegramInteraction, User
from app.telegram_interactions import cleanup_due_interactions


class TelegramInteractionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
                               'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(User(username='submitter', email='submitter@example.test', password_hash='unused',
                            telegram_user_id='42', telegram_chat_id='42'))
        self.config(telegram_webhook_secret='secret', telegram_bot_username='OurBot',
                    builtin_submitcoa_enabled='true', builtin_submitcoa_allow_non_private='true',
                    builtin_submitcoa_allowed_chat_ids='-1001', builtin_submitcoa_allowed_thread_ids='7',
                    builtin_publicresults_allow_non_private='true')
        self.client = self.app.test_client()
        self.api_calls = []
        self.next_id = 100

        def api(method, payload):
            self.api_calls.append((method, payload))
            self.next_id += 1
            if method == 'sendMessage':
                field = 'ephemeral_message_id' if 'ephemeral_message_parameters' in payload else 'message_id'
                return True, {'result': {field: self.next_id}}
            return True, {'result': True}

        upload = io.BytesIO(b'pdf-content')
        upload.filename = 'coa.pdf'
        self.patches = [
            patch('app.notifications._telegram_api_post', side_effect=api),
            patch('app.routes.send_telegram_chat_message', return_value=True),
            patch('app.routes.enqueue_analysis', return_value=SimpleNamespace(id=12)),
            patch('app.routes.download_telegram_photo', return_value=upload),
            patch('app.routes.upload_result_image', return_value='public-results/test.pdf'),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def config(self, **values):
        for key, value in values.items():
            row = NotificationConfig.query.filter_by(key=key).first()
            if row is None:
                row = NotificationConfig(key=key)
                db.session.add(row)
            row.value = value
        db.session.commit()

    def message(self, text=None, **extra):
        message = {'message_id': self.next_id + 1000, 'chat': {'id': -1001, 'type': 'supergroup'},
                   'message_thread_id': 7, 'from': {'id': 42}}
        if text is not None:
            message['text'] = text
        message.update(extra)
        response = self.client.post('/telegram/webhook', json={'message': message},
                                    headers={'X-Telegram-Bot-Api-Secret-Token': 'secret'})
        self.assertEqual(response.status_code, 200)
        return message

    def callback(self, row, data='pr:close', user_id=42):
        field = 'ephemeral_message_id' if row.is_ephemeral else 'message_id'
        response = self.client.post('/telegram/webhook', json={'callback_query': {
            'id': 'callback', 'from': {'id': user_id}, 'data': data,
            'message': {field: int(row.bot_message_id), 'chat': {'id': -1001, 'type': 'supergroup'},
                        'message_thread_id': 7}}},
            headers={'X-Telegram-Bot-Api-Secret-Token': 'secret'})
        self.assertEqual(response.status_code, 200)

    def prompt(self):
        self.message('/submitcoa@OurBot')
        return TelegramInteraction.query.filter_by(kind='coa_prompt').one()

    def test_prompt_reply_queues_attachment_and_caption_link(self):
        prompt = self.prompt()
        self.message(caption='Certificate https://example.test/coa.pdf',
                     document={'file_id': 'file', 'file_name': 'coa.pdf', 'mime_type': 'application/pdf'},
                     reply_to_message={'message_id': int(prompt.bot_message_id)})
        result = PublicResult.query.one()
        self.assertEqual(result.results_image_key, 'public-results/test.pdf')
        self.assertEqual(result.results_link, 'https://example.test/coa.pdf')
        self.assertEqual(result.publication_status, 'queued')
        self.assertIsNotNone(prompt.closed_at)
        self.assertEqual(self.api_calls[0][1]['reply_markup'], {'force_reply': True, 'selective': True})

    def test_hidden_link_reply_is_supported(self):
        prompt = self.prompt()
        self.message('My certificate', entities=[{'type': 'text_link', 'offset': 0, 'length': 14,
                     'url': 'https://example.test/coa.pdf'}],
                     reply_to_message={'message_id': int(prompt.bot_message_id)})
        self.assertEqual(PublicResult.query.one().results_link, 'https://example.test/coa.pdf')

    def test_prompt_rejects_wrong_user_topic_expiry_and_reuse(self):
        prompt = self.prompt()
        reply = {'reply_to_message': {'message_id': int(prompt.bot_message_id)}}
        self.message('https://example.test/a.pdf', **reply, **{'from': {'id': 99}})
        self.message('https://example.test/a.pdf', **reply, message_thread_id=8)
        prompt.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.message('https://example.test/a.pdf', **reply)
        self.assertEqual(PublicResult.query.count(), 0)
        prompt.expires_at = datetime.utcnow() + timedelta(hours=1)
        db.session.commit()
        self.message('https://example.test/a.pdf', **reply)
        self.message('https://example.test/a.pdf', **reply)
        self.assertEqual(PublicResult.query.count(), 1)

    def test_watch_requires_opt_in_and_exact_scope(self):
        self.message('https://example.test/coa.pdf')
        self.assertEqual(PublicResult.query.count(), 0)
        self.config(builtin_submitcoa_watch_enabled='true')
        self.message('https://example.test/coa.pdf', message_thread_id=8)
        self.message('https://example.test/coa.pdf', chat={'id': -1002, 'type': 'supergroup'})
        self.assertEqual(PublicResult.query.count(), 0)
        self.message('Here is a COA https://example.test/coa.pdf')
        self.assertEqual(PublicResult.query.count(), 1)

    def test_watch_empty_allowlist_never_collects_everywhere(self):
        self.config(builtin_submitcoa_watch_enabled='true', builtin_submitcoa_allowed_chat_ids='')
        self.message('https://example.test/coa.pdf')
        self.assertEqual(PublicResult.query.count(), 0)

    def test_watch_requires_active_linked_user_and_ignores_other_commands(self):
        self.config(builtin_submitcoa_watch_enabled='true')
        self.message('https://example.test/a.pdf', **{'from': {'id': 99}})
        self.message('/submitcoa@OtherBot https://example.test/a.pdf')
        self.message('/help https://example.test/a.pdf')
        user = User.query.one()
        user.is_active = False
        db.session.commit()
        self.message('https://example.test/a.pdf')
        self.assertEqual(PublicResult.query.count(), 0)

    def test_watch_photo_and_replay_guard(self):
        self.config(builtin_submitcoa_watch_enabled='true')
        message = self.message(photo=[{'file_id': 'photo'}])
        # Telegram redelivery with the same update ID is ignored.
        for _ in range(2):
            self.client.post('/telegram/webhook', json={'update_id': 500, 'message': message},
                             headers={'X-Telegram-Bot-Api-Secret-Token': 'secret'})
        self.assertEqual(PublicResult.query.count(), 2)

    def test_ephemeral_menu_navigation_and_close_delete_both_messages(self):
        source = self.message('/publicresults')
        row = TelegramInteraction.query.one()
        self.assertTrue(row.is_ephemeral)
        self.assertEqual(self.api_calls[0][1]['ephemeral_message_parameters'], {'receiver_user_id': 42})
        self.callback(row, 'pr:tags:1')
        self.assertTrue(any(method == 'editEphemeralMessageText' for method, _ in self.api_calls))
        self.callback(row)
        deletes = [(method, payload) for method, payload in self.api_calls if method.startswith('delete')]
        self.assertEqual([method for method, _ in deletes], ['deleteEphemeralMessage', 'deleteMessage'])
        self.assertEqual(deletes[1][1]['message_id'], source['message_id'])
        self.assertTrue(row.cleanup_complete)

    def test_shared_menu_only_requester_can_close(self):
        self.config(builtin_publicresults_ephemeral='false')
        self.message('/publicresults')
        row = TelegramInteraction.query.one()
        self.callback(row, user_id=99)
        self.assertIsNone(row.closed_at)
        self.assertFalse(any(method.startswith('delete') for method, _ in self.api_calls))
        self.callback(row)
        self.assertEqual(sum(method == 'deleteMessage' for method, _ in self.api_calls), 2)

    def test_timeout_durable_cleanup_and_partial_failure_retry(self):
        self.config(builtin_publicresults_ephemeral='false', builtin_publicresults_timeout_seconds='60')
        self.message('/publicresults')
        row = TelegramInteraction.query.one()
        self.assertAlmostEqual((row.expires_at - datetime.utcnow()).total_seconds(), 60, delta=3)
        self.assertEqual(cleanup_due_interactions(), 0)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        with patch('app.telegram_interactions.delete_telegram_message', side_effect=[True, False]) as delete:
            self.assertEqual(cleanup_due_interactions(), 1)
        self.assertEqual(delete.call_count, 2)
        self.assertTrue(row.menu_deleted)
        self.assertFalse(row.cleanup_complete)
        row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        with patch('app.telegram_interactions.delete_telegram_message', return_value=True) as delete:
            self.assertEqual(cleanup_due_interactions(), 1)
        delete.assert_called_once_with('-1001', row.command_message_id)
        self.assertTrue(row.cleanup_complete)

    def test_expired_callback_closes_instead_of_navigating(self):
        self.message('/publicresults')
        row = TelegramInteraction.query.one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        self.callback(row, 'pr:tags:1')
        self.assertIsNotNone(row.closed_at)
        self.assertFalse(any(method.startswith('edit') for method, _ in self.api_calls))

    def test_ephemeral_api_failure_falls_back_in_same_topic_with_navigation_and_cleanup(self):
        with patch('app.notifications._telegram_api_post', side_effect=[
                (False, {}), (True, {'result': {'message_id': 555}})]) as api, \
                patch('app.routes.send_telegram_chat_message') as notice:
            source = self.message('/publicresults')
        self.assertEqual(api.call_count, 2)
        first = api.call_args_list[0].args[1]
        fallback = api.call_args_list[1].args[1]
        self.assertIn('ephemeral_message_parameters', first)
        self.assertNotIn('ephemeral_message_parameters', fallback)
        self.assertEqual(fallback['chat_id'], '-1001')
        self.assertEqual(fallback['message_thread_id'], 7)
        self.assertEqual(fallback['text'], first['text'])
        self.assertEqual(fallback['reply_markup'], first['reply_markup'])
        notice.assert_not_called()
        row = TelegramInteraction.query.one()
        self.assertFalse(row.is_ephemeral)
        self.assertEqual(row.bot_message_id, '555')
        self.assertEqual(row.command_message_id, str(source['message_id']))
        self.assertAlmostEqual((row.expires_at - datetime.utcnow()).total_seconds(), 300, delta=3)
        self.callback(row, 'pr:tags:1')
        self.assertTrue(any(method == 'editMessageText' for method, _ in self.api_calls))
        self.callback(row)
        self.assertTrue(row.cleanup_complete)
        self.assertEqual(sum(method == 'deleteMessage' for method, _ in self.api_calls), 2)

    def test_fallback_from_ephemeral_command_removes_ephemeral_reply_parameters(self):
        with patch('app.notifications._telegram_api_post', side_effect=[
                (False, {}), (True, {'result': {'message_id': 556}})]) as api:
            self.message('/publicresults', ephemeral_message_id=999, message_id=0)
        fallback = api.call_args_list[1].args[1]
        self.assertNotIn('reply_parameters', fallback)
        self.assertNotIn('ephemeral_message_parameters', fallback)
        row = TelegramInteraction.query.one()
        self.assertFalse(row.is_ephemeral)
        self.assertTrue(row.command_is_ephemeral)
        self.callback(row)
        self.assertEqual([method for method, _ in self.api_calls if method.startswith('delete')],
                         ['deleteMessage', 'deleteEphemeralMessage'])

    def test_failed_public_fallback_does_not_create_cleanup_record(self):
        with patch('app.notifications._telegram_api_post', return_value=(False, {})) as api, \
                patch('app.routes.send_telegram_chat_message') as notice:
            self.message('/publicresults')
        self.assertEqual(api.call_count, 2)
        notice.assert_not_called()
        self.assertEqual(TelegramInteraction.query.count(), 0)

    def test_existing_analysis_process_cleans_expired_menus_with_empty_queue(self):
        self.message('/publicresults')
        row = TelegramInteraction.query.one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        interaction_id = row.id
        with patch('app.result_analysis.jobs.process_next_run', return_value=None) as analyze, \
                patch('app.report_instance_event'):
            result = self.app.test_cli_runner().invoke(args=['result-analysis-worker', '--once'])
        self.assertEqual(result.exit_code, 0, result.output)
        analyze.assert_called_once()
        db.session.expire_all()
        row = db.session.get(TelegramInteraction, interaction_id)
        self.assertTrue(row.cleanup_complete)

    def test_cleanup_failure_does_not_block_existing_analysis_process(self):
        with patch('app.telegram_interactions.cleanup_due_interactions', side_effect=RuntimeError('cleanup unavailable')), \
                patch('app.result_analysis.jobs.process_next_run', return_value=None) as analyze, \
                patch('app.report_instance_event'):
            result = self.app.test_cli_runner().invoke(args=['result-analysis-worker', '--once'])
        self.assertEqual(result.exit_code, 0, result.output)
        analyze.assert_called_once()

    def test_private_menu_timeout_deletes_menu_and_command(self):
        self.message('/publicresults', chat={'id': 42, 'type': 'private'}, message_thread_id=None)
        row = TelegramInteraction.query.one()
        self.assertFalse(row.is_ephemeral)
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        cleanup_due_interactions()
        self.assertTrue(row.cleanup_complete)
        self.assertEqual(sum(method == 'deleteMessage' for method, _ in self.api_calls), 2)

    def test_ephemeral_command_is_replied_to_and_deleted_as_ephemeral(self):
        self.message('/publicresults', ephemeral_message_id=999, message_id=0)
        row = TelegramInteraction.query.one()
        self.assertEqual(self.api_calls[0][1]['reply_parameters'], {'ephemeral_message_id': 999})
        self.callback(row)
        self.assertEqual(sum(method == 'deleteEphemeralMessage' for method, _ in self.api_calls), 2)

    def test_reused_ephemeral_id_is_not_deleted_by_older_cleanup(self):
        self.message('/publicresults')
        old = TelegramInteraction.query.one()
        self.next_id = int(old.bot_message_id) - 1
        self.message('/publicresults')
        new = TelegramInteraction.query.order_by(TelegramInteraction.id.desc()).first()
        self.assertEqual(new.bot_message_id, old.bot_message_id)
        db.session.refresh(old)
        self.assertTrue(old.menu_deleted)
        self.assertIsNotNone(old.closed_at)
        cleanup_due_interactions()
        self.assertFalse(any(method == 'deleteEphemeralMessage' for method, _ in self.api_calls))

    def test_cleanup_abandons_missing_permissions_after_bounded_retries(self):
        self.message('/publicresults')
        row = TelegramInteraction.query.one()
        row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.session.commit()
        with patch('app.telegram_interactions.delete_telegram_message', return_value=False), \
                patch('app.telegram_interactions.delete_telegram_ephemeral_message', return_value=False):
            for _ in range(5):
                row.next_attempt_at = None
                db.session.commit()
                cleanup_due_interactions()
        self.assertTrue(row.cleanup_complete)
        self.assertFalse(row.command_deleted)
        self.assertEqual(row.cleanup_attempts, 5)

    def test_settings_persist_and_reject_unscoped_watch_and_invalid_timeout(self):
        user = User.query.one()
        user.is_admin = True
        user.set_password('settings-secret')
        db.session.commit()
        self.client.post('/login', data={'username': 'submitter', 'password': 'settings-secret'})
        path = '/admin/settings/commands/builtins'
        page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Telegram privacy and cleanup', page.data)
        values = {'submitcoa_enabled': 'y', 'submitcoa_allow_non_private': 'y',
                  'submitcoa_watch_enabled': 'y', 'submitcoa_allowed_chat_ids': '',
                  'publicresults_timeout_seconds': '60', 'publicresults_ephemeral': 'y'}
        response = self.client.post(path, data=values)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'explicit allowed submission Chat IDs', response.data)
        values['submitcoa_allowed_chat_ids'] = '-1001'
        values['publicresults_timeout_seconds'] = '1'
        response = self.client.post(path, data=values)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Number must be between', response.data)
        values['publicresults_timeout_seconds'] = '60'
        response = self.client.post(path, data=values)
        self.assertEqual(response.status_code, 302)
        db.session.expire_all()
        self.assertEqual(NotificationConfig.query.filter_by(key='builtin_submitcoa_watch_enabled').one().value, 'true')
        self.assertEqual(NotificationConfig.query.filter_by(key='builtin_publicresults_timeout_seconds').one().value, '60')


if __name__ == '__main__':
    unittest.main()
