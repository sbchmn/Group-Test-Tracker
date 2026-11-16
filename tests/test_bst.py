import io
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from PIL import Image

from app import create_app, db
from app.models import (BSTTopic, BSTVendor, BSTEvent, BSTNotice, BSTMessage, User, NotificationConfig,
                        GroupTest, Participation, ResultAnalysisRun)
from app import bst_service as bst
from app.bst_moderation import moderate, maintain_messages


DATA = {'vendor_name': 'Vendor One', 'email': 'vendor@example.com', 'guarantees': 'Replacement for damaged goods.',
        'dispute_contact': '@vendor_support', 'dispute_process': 'Contact support within 14 days.'}


class BSTTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:'})
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.admin = User(username='bst-admin', email='admin@example.com', password_hash='unused',
                          is_admin=True, telegram_user_id='99', telegram_chat_id='99', notification_channel='discord', discord_user_id='199')
        db.session.add(self.admin)
        db.session.add_all([NotificationConfig(key='telegram_webhook_secret', value='secret'),
                           NotificationConfig(key='telegram_bot_username', value='OurBot')])
        self.topic = BSTTopic(chat_id='-1001', thread_id=7, name='Vendor listings', code='code', enabled=True,
                              options={key: default for key, (_, default) in bst.OPTIONS.items()})
        db.session.add(self.topic)
        db.session.commit()
        self.client = self.app.test_client()
        self.calls = []
        self.next_id = 500
        self.group_admins = {'7'}

        def api(method, payload):
            self.calls.append((method, payload))
            if method == 'getMe':
                return True, {'result': {'id': 900, 'username': 'OurBot'}}
            if method == 'getChatMember':
                uid = str(payload['user_id'])
                admin = (uid in self.group_admins and str(payload['chat_id']) == '-1001') or uid == '900'
                return True, {'result': {'status': 'administrator' if admin else 'member', 'can_delete_messages': admin}}
            if method == 'getChatAdministrators':
                return True, {'result': [{'user': {'id': int(uid)}, 'status': 'administrator'} for uid in self.group_admins]}
            if method == 'sendMessage':
                self.next_id += 1
                return True, {'result': {'message_id': self.next_id}}
            return True, {'result': True}

        self.patches = [patch('app.bst_service._telegram_api_post', side_effect=api),
                        patch('app.bst_bot._telegram_api_post', side_effect=api),
                        patch('app.notifications._telegram_api_post', side_effect=api),
                        patch('app.bst_service.send_notification_message', return_value=True),
                        patch('app.bst_service.send_mailjet_message', return_value=True),
                        patch('app.bst_moderation.delete_telegram_message', return_value=True)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def vendor(self, uid='42', approved=False):
        vendor = bst.get_vendor(self.topic, uid)
        vendor.draft = dict(DATA)
        db.session.commit()
        bst.submit(vendor, vendor.version)
        if approved:
            bst.decide(vendor, 'approve', vendor.version, uid='7')
        return vendor

    def post(self, message=None, callback=None, edited=False, update_id=None):
        payload = {'callback_query': callback} if callback else {'edited_message' if edited else 'message': message}
        if update_id is not None:
            payload['update_id'] = update_id
        response = self.client.post('/telegram/webhook', json=payload,
                                    headers={'X-Telegram-Bot-Api-Secret-Token': 'secret'})
        self.assertEqual(response.status_code, 200)
        return response

    def dm(self, text, uid=42):
        return self.post({'message_id': self.next_id + 1, 'chat': {'id': uid, 'type': 'private'}, 'from': {'id': uid}, 'text': text})

    def callback(self, data, uid=42):
        return self.post(callback={'id': 'callback', 'from': {'id': uid}, 'data': 'bs:' + data,
                                  'message': {'message_id': 400, 'chat': {'id': uid, 'type': 'private'}}})

    def listing(self, uid=42, **values):
        message = {'message_id': 100, 'chat': {'id': -1001, 'type': 'supergroup'}, 'from': {'id': uid},
                   'message_thread_id': 7, 'text': 'A listing'}
        message.update(values)
        return message

    def login(self):
        self.admin.set_password('secret')
        db.session.commit()
        self.client.post('/login', data={'username': 'bst-admin', 'password': 'secret'})

    def test_unlinked_applicant_can_complete_and_submit_in_dm(self):
        self.dm('/start bst_code')
        for value in DATA.values():
            self.dm(value)
        vendor = BSTVendor.query.one()
        self.assertEqual(vendor.draft, DATA)
        self.assertEqual(User.query.filter_by(telegram_user_id='42').count(), 0)
        self.callback(f'submit:{vendor.id}:{vendor.version}')
        self.assertEqual(vendor.status, 'pending')
        self.assertEqual(BSTNotice.query.filter_by(recipient=f'gtm:{self.admin.id}').count(), 1)

    def test_reopening_link_resumes_draft_and_does_not_duplicate_pending(self):
        self.dm('/start bst_code')
        self.dm('My vendor')
        self.dm('/start bst_code')
        self.assertEqual(BSTVendor.query.count(), 1)
        self.assertIn('email', self.calls[-1][1]['text'].lower())
        vendor = BSTVendor.query.one()
        vendor.draft = DATA
        db.session.commit()
        bst.submit(vendor, vendor.version)
        self.dm('/start bst_code')
        self.assertEqual(BSTVendor.query.count(), 1)
        self.assertEqual(vendor.status, 'pending')

    def test_applicant_cannot_read_or_edit_another_application(self):
        vendor = self.vendor()
        self.callback(f'self:{vendor.id}', uid=43)
        self.assertIn('not available', self.calls[-1][1]['text'])
        self.callback(f'edit:{vendor.id}:email', uid=43)
        self.assertIn('not available', self.calls[-1][1]['text'])

    def test_group_admin_without_gtm_link_can_review_and_configure(self):
        vendor = self.vendor()
        self.callback(f'decide:{vendor.id}:approve:{vendor.version}', uid=7)
        self.assertTrue(vendor.is_approved)
        self.assertEqual(User.query.filter_by(telegram_user_id='7').count(), 0)
        self.callback(f'toggle:{self.topic.id}:allow_links:{self.topic.version}', uid=7)
        self.assertTrue(bst.options(self.topic)['allow_links'])

    def test_linked_gtm_admin_is_authorized_without_group_admin_role(self):
        vendor = self.vendor()
        bst.decide(vendor, 'approve', vendor.version, uid='99')
        self.assertTrue(vendor.is_approved)

    def test_non_admin_cannot_manage_or_change_topic(self):
        vendor = self.vendor()
        with self.assertRaises(bst.BSTError):
            bst.decide(vendor, 'approve', vendor.version, uid='42')
        self.callback(f'toggle:{self.topic.id}:allow_links:{self.topic.version}')
        self.assertFalse(bst.options(self.topic)['allow_links'])

    def test_removed_group_admin_loses_review_authority(self):
        vendor = self.vendor()
        self.assertTrue(bst.can_manage('7', self.topic.chat_id))
        self.group_admins.clear()
        with self.assertRaises(bst.BSTError):
            bst.decide(vendor, 'approve', vendor.version, uid='7')

    def test_reasons_required_and_stale_decision_cannot_duplicate_notices(self):
        vendor = self.vendor()
        version = vendor.version
        with self.assertRaises(bst.BSTError):
            bst.decide(vendor, 'deny', version, '', uid='7')
        bst.decide(vendor, 'approve', version, uid='7')
        count = BSTNotice.query.count()
        with self.assertRaises(bst.BSTError):
            bst.decide(vendor, 'deny', version, 'No', uid='7')
        self.assertEqual(BSTNotice.query.count(), count)

    def test_changes_and_denial_allow_reapplication_revocation_requires_restore(self):
        vendor = self.vendor()
        bst.decide(vendor, 'changes', vendor.version, 'Explain your guarantee.', uid='7')
        self.assertEqual(vendor.status, 'changes')
        bst.save_answer(vendor, 'guarantees', 'Replacement or refund.', vendor.version)
        bst.submit(vendor, vendor.version)
        bst.decide(vendor, 'deny', vendor.version, 'Insufficient terms.', uid='7')
        bst.save_answer(vendor, 'guarantees', 'Replacement, refund, and support.', vendor.version)
        bst.submit(vendor, vendor.version)
        bst.decide(vendor, 'approve', vendor.version, uid='7')
        bst.decide(vendor, 'revoke', vendor.version, 'Terms violated.', uid='7')
        with self.assertRaises(bst.BSTError):
            bst.submit(vendor, vendor.version)
        with self.assertRaises(bst.BSTError):
            bst.save_answer(vendor, 'vendor_name', 'New name', vendor.version)
        bst.decide(vendor, 'restore', vendor.version, 'Dispute resolved.', uid='7')
        self.assertTrue(bst.eligible(vendor))

    def test_profile_changes_do_not_replace_approved_information_until_reviewed(self):
        vendor = self.vendor(approved=True)
        bst.save_answer(vendor, 'guarantees', 'New guarantee.', vendor.version)
        self.assertTrue(bst.eligible(vendor))
        bst.submit(vendor, vendor.version)
        self.assertEqual(vendor.approved['guarantees'], DATA['guarantees'])
        bst.decide(vendor, 'deny', vendor.version, 'Keep original guarantee.', uid='7')
        self.assertTrue(bst.eligible(vendor))
        bst.submit(vendor, vendor.version)
        bst.decide(vendor, 'approve', vendor.version, uid='7')
        self.assertEqual(vendor.approved['guarantees'], 'New guarantee.')

    def test_preapproval_is_available_without_an_application_or_gtm_account(self):
        vendor = bst.preapprove(self.topic, '42', DATA, uid='7')
        self.assertTrue(bst.eligible(vendor))
        self.assertEqual(vendor.approved['vendor_name'], DATA['vendor_name'])
        with self.assertRaises(bst.BSTError):
            bst.preapprove(self.topic, '42', DATA, uid='7')

    def test_email_verification_required_for_submission_and_admin_created_posting(self):
        self.topic.options = dict(self.topic.options, verify_email=True)
        db.session.commit()
        vendor = bst.preapprove(self.topic, '42', DATA, uid='7')
        self.assertFalse(bst.eligible(vendor))
        with patch('app.bst_service.send_mailjet_message', return_value=True) as mail:
            bst.send_verification(vendor)
            code = re.search(r'code is (\d{6})', mail.call_args.args[2]).group(1)
        self.assertNotIn(code, str(vendor.verification))
        with self.assertRaises(bst.BSTError):
            bst.send_verification(vendor)
        bst.verify_email(vendor, code)
        self.assertTrue(bst.eligible(vendor))
        bst.save_answer(vendor, 'email', 'other@example.com', vendor.version)
        with self.assertRaises(bst.BSTError):
            bst.submit(vendor, vendor.version)
        self.assertTrue(bst.eligible(vendor))

    def test_verification_attempt_budget_expiration_and_changed_email(self):
        vendor = bst.get_vendor(self.topic, '42')
        vendor.draft = DATA
        db.session.commit()
        bst.send_verification(vendor)
        for _ in range(5):
            with self.assertRaises(bst.BSTError):
                bst.verify_email(vendor, 'invalid')
        self.assertEqual(vendor.verification['attempts'], 5)
        with self.assertRaises(bst.BSTError):
            bst.verify_email(vendor, '000000')
        vendor.verification = dict(vendor.verification, expires=(datetime.utcnow() - timedelta(minutes=1)).isoformat())
        db.session.commit()
        with self.assertRaises(bst.BSTError):
            bst.verify_email(vendor, '000000')

    def test_admin_notifications_use_configured_channels_and_skip_unlinked_admins(self):
        db.session.add(User(username='unlinked-admin', email='unlinked@example.com', password_hash='unused', is_admin=True))
        db.session.commit()
        vendor = self.vendor()
        self.assertEqual([n.recipient for n in BSTNotice.query.all()], [f'gtm:{self.admin.id}'])
        with patch('app.bst_service.send_notification_message', return_value=True) as deliver:
            bst.deliver_notices()
        self.assertEqual(deliver.call_args.args[1], 'discord')
        self.assertTrue(BSTNotice.query.one().complete)

    def test_every_unapproved_sender_is_removed_in_exact_topic_only(self):
        with patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete:
            self.assertTrue(moderate(self.listing(uid=7)))
            delete.assert_called_once_with('-1001', 100)
            self.assertFalse(moderate(self.listing(message_thread_id=8)))
            self.assertFalse(moderate(self.listing(chat={'id': -1002, 'type': 'supergroup'})))
        self.assertEqual(BSTEvent.query.filter_by(action='reminder').count(), 1)

    def test_approved_vendor_posts_compliant_content_without_account_link(self):
        self.vendor(approved=True)
        with patch('app.bst_moderation.delete_telegram_message') as delete:
            self.assertTrue(moderate(self.listing()))
            moderate(self.listing(text=None, photo=[{'file_id': 'photo'}], caption='A listing'))
        delete.assert_not_called()

    def test_links_other_media_captions_text_image_requirements_and_forwards(self):
        self.vendor(approved=True)
        cases = [({'text': 'https://example.com'}, {}), ({'video': {'file_id': 'v'}}, {}),
                 ({'text': 'View', 'entities': [{'type': 'text_link', 'url': 'https://example.com'}]}, {}),
                 ({'text': None, 'photo': [{'file_id': 'p'}], 'caption': 'caption'}, {'allow_captions': False}),
                 ({'text': 'Text only'}, {'require_image': True}),
                 ({'forward_origin': {'type': 'user'}}, {})]
        for message, override in cases:
            with self.subTest(message=message, override=override):
                self.topic.options = {key: default for key, (_, default) in bst.OPTIONS.items()} | override
                db.session.commit()
                with patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete:
                    moderate(self.listing(**message))
                    self.assertTrue(delete.called)

    def test_image_document_checks_actual_bytes(self):
        self.vendor(approved=True)
        self.topic.options = dict(self.topic.options, allow_documents=True)
        db.session.commit()
        image = io.BytesIO()
        Image.new('RGB', (2, 2)).save(image, format='PNG')
        for raw, allowed in [(image.getvalue(), True), (b'not an image', False)]:
            with patch('app.bst_moderation.download_telegram_photo', return_value=io.BytesIO(raw)), \
                    patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete:
                moderate(self.listing(text=None, document={'file_id': 'doc', 'mime_type': 'image/png'}))
                self.assertEqual(delete.called, not allowed)

    def test_albums_evaluate_caption_across_fragments_and_edits(self):
        self.vendor(approved=True)
        self.topic.options = dict(self.topic.options, require_caption=True)
        db.session.commit()
        for mid, caption in [(100, 'Album caption'), (101, '')]:
            moderate(self.listing(message_id=mid, text=None, photo=[{'file_id': 'p'}], media_group_id='album', caption=caption))
        BSTMessage.query.update({'due_at': datetime.utcnow() - timedelta(seconds=1)})
        db.session.commit()
        maintain_messages()
        self.assertEqual(BSTMessage.query.filter_by(action='album_ok').count(), 2)
        moderate(self.listing(message_id=100, text=None, photo=[{'file_id': 'p'}], media_group_id='album', caption=''))
        BSTMessage.query.update({'due_at': datetime.utcnow() - timedelta(seconds=1)})
        db.session.commit()
        maintain_messages()
        self.assertEqual(BSTMessage.query.filter_by(action='delete').count(), 2)
        with patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete:
            maintain_messages()
        self.assertEqual(delete.call_count, 2)

    def test_edited_message_is_moderated_without_replaying_commands(self):
        self.vendor(approved=True)
        with patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete, \
                patch('app.routes._submit_telegram_coa') as submit:
            self.post(self.listing(text='/submitcoa https://example.com/coa.pdf'), edited=True)
        delete.assert_called_once()
        submit.assert_not_called()

    def test_failed_deletion_retries_without_falsely_sending_removal_notice(self):
        with patch('app.bst_moderation.delete_telegram_message', return_value=False):
            moderate(self.listing())
        self.assertEqual(BSTMessage.query.filter_by(action='delete').count(), 1)
        self.assertEqual(BSTEvent.query.filter_by(action='reminder').count(), 0)
        BSTMessage.query.update({'due_at': datetime.utcnow() - timedelta(seconds=1)})
        db.session.commit()
        maintain_messages()
        self.assertEqual(BSTMessage.query.filter_by(action='delete').count(), 0)
        self.assertEqual(BSTEvent.query.filter_by(action='reminder').count(), 1)

    def test_bot_permissions_and_dependent_options_checked_before_enabling(self):
        with patch('app.bst_service._telegram_api_post', return_value=(False, {})):
            with self.assertRaises(bst.BSTError):
                bst.save_topic('-1001', 7, 'Vendors', self.topic.options, True, self.topic, self.topic.version, uid='99')
        with self.assertRaises(bst.BSTError):
            bst.validate_options({'allow_photos': False, 'allow_albums': True})

    def test_web_management_and_one_mixed_queue_keep_bst_out_of_join_bulk_actions(self):
        vendor = self.vendor()
        test = GroupTest(title='Shared Queue Test', status='recruiting', created_by=self.admin.id)
        db.session.add(test)
        db.session.flush()
        part = Participation(user_id=self.admin.id, group_test_id=test.id, name='A participant', approved=False, denied=False)
        run = ResultAnalysisRun(group_test_id=test.id, source_kind='link', source_reference='https://example.com',
                                provider='openai', provider_model='model', status='failed', error_message='Failure')
        db.session.add_all([part, run])
        db.session.commit()
        self.login()
        response = self.client.get('/admin/action-queue')
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('BST Application', body)
        self.assertIn('Join Request', body)
        self.assertIn('Inspect Failure', body)
        self.assertEqual(body.count('<table'), 1)
        self.assertEqual(body.count('class="part-checkbox"'), 1)
        for path in ['/admin/bst', f'/admin/bst/vendors/{vendor.id}', f'/admin/bst/topics/{self.topic.id}', '/admin/bst/vendors/new']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.client.post('/admin/action-queue/approve-selected', data={'part_ids': [str(part.id)]})
        db.session.refresh(vendor)
        self.assertEqual(vendor.status, 'pending')

    def test_web_decision_shared_with_bot_and_preserves_queue_destination(self):
        vendor = self.vendor()
        self.login()
        response = self.client.post(f'/admin/bst/vendors/{vendor.id}/decision',
                                    data={'action': 'approve', 'version': vendor.version, 'return_to': 'queue', 'type': 'bst', 'page': 2})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/admin/action-queue', response.location)
        self.assertIn('type=bst', response.location)
        self.assertTrue(vendor.is_approved)
        self.callback(f'view:{vendor.id}', uid=7)
        self.assertTrue(any('Status: approved' in payload.get('text', '') for _, payload in self.calls))

    def test_duplicate_updates_do_not_resubmit_or_duplicate_notifications(self):
        self.dm('/start bst_code')
        vendor = BSTVendor.query.one()
        vendor.draft = DATA
        db.session.commit()
        callback = {'id': 'one', 'from': {'id': 42}, 'data': f'bs:submit:{vendor.id}:{vendor.version}',
                    'message': {'message_id': 1, 'chat': {'id': 42, 'type': 'private'}}}
        self.post(callback=callback, update_id=88)
        self.post(callback=callback, update_id=88)
        self.assertEqual(BSTNotice.query.count(), 1)

    def test_topic_setup_and_admin_creation_work_entirely_through_bot(self):
        self.dm('/bstadmin -1001 9', uid=7)
        topic = BSTTopic.query.filter_by(thread_id=9).one()
        self.assertFalse(topic.enabled)
        self.callback(f'toggle:{topic.id}:enabled:{topic.version}', uid=7)
        self.assertTrue(topic.enabled)
        self.callback(f'create:{topic.id}', uid=7)
        for value in ['12345', *DATA.values()]:
            self.dm(value, uid=7)
        self.callback(f'preapprove:{topic.id}', uid=7)
        vendor = BSTVendor.query.filter_by(topic_id=topic.id, telegram_user_id='12345').one()
        self.assertTrue(bst.eligible(vendor))

    def test_web_config_and_preapproval_validate_and_persist(self):
        self.login()
        values = {'chat_id': '-1001', 'thread_id': 9, 'name': 'Second listings', 'enabled': 'y',
                  'allow_text': 'y', 'allow_photos': 'y', 'allow_albums': 'y', 'allow_captions': 'y', 'verify_email': 'y'}
        response = self.client.post('/admin/bst/topics/new', data=values)
        self.assertEqual(response.status_code, 302)
        topic = BSTTopic.query.filter_by(thread_id=9).one()
        self.assertTrue(bst.options(topic)['verify_email'])
        response = self.client.post('/admin/bst/vendors/new', data=dict(DATA, topic_id=topic.id, telegram_user_id='45678'))
        self.assertEqual(response.status_code, 302)
        vendor = BSTVendor.query.filter_by(topic_id=topic.id).one()
        self.assertTrue(vendor.is_approved)
        self.assertFalse(bst.eligible(vendor))

    def test_queue_filters_and_pagination_apply_across_workload_types(self):
        from app.admin_queue import build_queue
        for number in range(27):
            vendor = bst.get_vendor(self.topic, str(10000 + number))
            vendor.draft = dict(DATA, vendor_name=f'Vendor {number}')
            vendor.status = 'pending'
            vendor.submitted_at = datetime.utcnow() + timedelta(seconds=number)
        db.session.commit()
        page, items = build_queue('closed', '', 1, 'all')
        self.assertEqual(page.total, 27)
        self.assertEqual(len(items), 25)
        self.assertTrue(all(item.kind == 'bst' for item in items))
        page, items = build_queue('all', '', 2, 'bst')
        self.assertEqual(len(items), 2)
        page, items = build_queue('all', 'Vendor 26', 1, 'all')
        self.assertEqual(len(items), 1)
        page, items = build_queue('all', '', 1, 'join')
        self.assertEqual(len(items), 0)

    def test_admin_notifications_escape_email_body_including_transport_fallback(self):
        from app.notifications import send_notification_message
        vendor = bst.get_vendor(self.topic, '42')
        vendor.draft = dict(DATA, vendor_name='<img src=x onerror=alert(1)>')
        db.session.commit()
        bst.submit(vendor, vendor.version)
        with patch('app.bst_service.send_notification_message', return_value=True) as deliver:
            bst.deliver_notices()
        email_body = deliver.call_args.kwargs['email_body']
        self.assertNotIn('<img', email_body)
        self.assertIn('&lt;img', email_body)
        with patch.dict('app.notifications._CHANNEL_SENDERS', {'discord': lambda *args: False}), \
                patch('app.notifications.send_mailjet_message', return_value=True) as email:
            send_notification_message(self.admin, 'discord', 'Subject', '<img src=x>', email_body=email_body)
        self.assertEqual(email.call_args.args[2], email_body)

    def test_bst_draft_does_not_capture_reply_to_unrelated_bot_workflow(self):
        self.dm('/start bst_code')
        vendor = BSTVendor.query.one()
        from app.bst_bot import handle_message
        handled = handle_message({'chat': {'id': 42, 'type': 'private'}, 'from': {'id': 42},
                                  'text': 'Some other correction', 'reply_to_message': {'message_id': 99999}}, '', '')
        self.assertFalse(handled)
        self.assertEqual(vendor.draft, {})

    def test_full_application_is_available_to_telegram_reviewers(self):
        vendor = self.vendor()
        vendor.draft = dict(vendor.draft, guarantees='Guarantees. ' * 200, dispute_process='Specific dispute process.')
        db.session.commit()
        self.callback(f'details:{vendor.id}', uid=7)
        bodies = [payload.get('text', '') for _, payload in self.calls]
        self.assertTrue(any('Specific dispute process.' in body for body in bodies))
        self.assertTrue(any(vendor.draft['guarantees'] in body for body in bodies))

    def test_reminders_are_rate_limited_and_failed_dms_use_temporary_topic_notice(self):
        from app.bst_moderation import reminder
        with patch('app.bst_moderation.send_telegram_interactive_message', side_effect=[None, '10001']) as send:
            reminder(self.topic, '42', 'Approval required.')
            reminder(self.topic, '42', 'Approval required.')
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args.args[0], '-1001')
        row = BSTMessage.query.filter_by(action='reminder').one()
        self.assertAlmostEqual((row.due_at - datetime.utcnow()).total_seconds(), 60, delta=3)

    def test_anonymous_posts_are_not_attributed_to_an_approved_admin(self):
        self.vendor(uid='7', approved=True)
        with patch('app.bst_moderation.delete_telegram_message', return_value=True) as delete:
            moderate(self.listing(uid=7, sender_chat={'id': -1001}))
        delete.assert_called_once()

    def test_same_update_cannot_run_bst_form_commands_from_edits(self):
        self.post({'message_id': 1, 'chat': {'id': 42, 'type': 'private'}, 'from': {'id': 42},
                   'text': '/start bst_code'}, edited=True)
        self.assertEqual(BSTVendor.query.count(), 0)

    def test_unlinked_start_and_help_offer_bst_without_requiring_gtm_registration(self):
        self.dm('/start')
        self.assertIn('BST applicants do not need a GTM account', self.calls[-1][1]['text'])
        self.dm('/help')
        self.assertIn('/bstadmin', self.calls[-1][1]['text'])
        self.assertEqual(User.query.filter_by(telegram_user_id='42').count(), 0)

    def test_cancelling_bot_decision_clears_old_reason_prompt(self):
        vendor = self.vendor()
        self.callback(f'decide:{vendor.id}:deny:{vendor.version}', uid=7)
        self.assertEqual(bst.conversation('7')['mode'], 'decision')
        self.callback(f'view:{vendor.id}', uid=7)
        self.assertEqual(bst.conversation('7'), {})
        self.dm('This is not a denial reason.', uid=7)
        self.assertEqual(vendor.status, 'pending')

    def test_notification_exceptions_are_bounded_and_do_not_retry_forever(self):
        self.vendor()
        row = BSTNotice.query.one()
        with patch('app.bst_service.send_notification_message', side_effect=RuntimeError('transport unavailable')):
            for _ in range(5):
                row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
                db.session.commit()
                bst.deliver_notices()
        self.assertTrue(row.complete)
        self.assertEqual(row.attempts, 5)

    def test_linked_group_admin_receives_configured_channel_without_gtm_admin_promotion(self):
        group_admin = User(username='group-admin', email='group-admin@example.com', password_hash='unused',
                           telegram_user_id='7', notification_channel='email', is_admin=False)
        db.session.add(group_admin)
        db.session.commit()
        self.vendor()
        self.assertEqual(BSTNotice.query.filter_by(recipient=f'gtm:{group_admin.id}').count(), 1)
        with patch('app.bst_service.send_notification_message', return_value=True) as send:
            bst.deliver_notices()
        channels = [call.args[1] for call in send.call_args_list]
        self.assertIn('email', channels)
        self.assertIn('discord', channels)
        self.assertFalse(group_admin.is_admin)

    def test_group_admin_authority_is_scoped_to_the_actual_group(self):
        other = BSTTopic(chat_id='-1002', thread_id=7, name='Other group', code='other', options={})
        db.session.add(other)
        db.session.commit()
        self.assertFalse(bst.can_manage('7', other.chat_id))
        self.assertTrue(bst.can_manage('7', self.topic.chat_id))


if __name__ == '__main__':
    unittest.main()
