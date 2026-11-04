import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask_migrate import downgrade, upgrade
from PIL import Image
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import GroupTest, NotificationConfig, Participation, PaymentOption, PaymentSubmission, User
from app.payments import explorer_url
from app.storage import StorageUploadError, upload_payment_proof


class PaymentProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            'TESTING': True, 'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(self.tmp.name) / 'test.db'),
            'NOTIFICATION_LOG_PATH': str(Path(self.tmp.name) / 'notifications.log'),
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            users = [User(username=name, email=name + '@example.test', is_admin=name == 'admin')
                     for name in ('member', 'admin', 'outsider')]
            for user in users:
                user.set_password('secret')
            db.session.add_all(users)
            db.session.flush()
            option = PaymentOption(label='Lab wallet', method_type='crypto', network='Base', wallet_address='0x123',
                                   proof_image_enabled=True, proof_transaction_enabled=True, proof_requirement='either')
            test = GroupTest(title='Proof test', created_by=users[1].id, status='ready_for_payment',
                             results_image_key='results/coa.jpg', payment_options=[option])
            db.session.add(test)
            db.session.flush()
            part = Participation(group_test_id=test.id, user_id=users[0].id, approved=True, amount_owed=50)
            db.session.add(part)
            db.session.commit()
            self.part_id, self.test_id, self.option_id = part.id, test.id, option.id
            self.user_id, self.admin_id = users[0].id, users[1].id
        self.login('member')

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def login(self, username):
        self.client.get('/logout')
        self.client.post('/login', data={'username': username, 'password': 'secret'})

    def detail(self):
        return self.client.get(f'/payments/{self.part_id}').get_json()

    def report(self, **overrides):
        payload = {'revision': self.detail()['revision'], 'amount': '50.00', 'option_id': self.option_id,
                   'transaction_id': '0x' + 'a' * 64}
        payload.update(overrides)
        with patch('app.routes._notify_payment_claim'):
            return self.client.post(f'/payments/{self.part_id}/report', data=payload)

    def review(self, decision, **overrides):
        payload = {'revision': self.detail()['revision'], 'decision': decision}
        payload.update(overrides)
        return self.client.post(f'/payments/{self.part_id}/review', data=payload)

    def test_either_requirement_and_positive_amount_enforced(self):
        response = self.report(transaction_id='')
        self.assertEqual(response.status_code, 400)
        self.assertIn('proof', response.json['errors'])
        for amount in ('0', '-1', 'NaN', 'Infinity', '12.345', '10000000000'):
            self.assertEqual(self.report(amount=amount).status_code, 400)
        self.assertEqual(self.report().status_code, 200)
        data = self.detail()
        self.assertTrue(data['pending'])
        self.assertFalse(data['paid'])
        self.assertEqual(data['latest']['explorer_url'], 'https://basescan.org/tx/0x' + 'a' * 64)
        self.assertEqual(self.client.get(f'/result-image/group-test/{self.test_id}').status_code, 403)

    def test_all_policy_optional_policy_and_disabled_proofs(self):
        with self.app.app_context():
            option = db.session.get(PaymentOption, self.option_id)
            option.proof_requirement = 'all'
            db.session.commit()
        self.assertIn('image', self.report().json['errors'])
        with self.app.app_context():
            option = db.session.get(PaymentOption, self.option_id)
            option.proof_requirement = 'optional'
            option.proof_transaction_enabled = False
            db.session.commit()
        self.assertIn('transaction_id', self.report().json['errors'])
        self.assertEqual(self.report(transaction_id='').status_code, 200)

    def test_image_only_satisfies_either_and_replacement_preserves_history(self):
        with patch('app.payments.upload_payment_proof', return_value='private/one.jpg'):
            self.assertEqual(self.report(transaction_id='', image=(io.BytesIO(b'image'), 'receipt.jpg')).status_code, 200)
        self.assertEqual(self.report(transaction_id='').status_code, 200)  # retained image
        self.assertEqual(self.report(transaction_id='', remove_image='true').status_code, 400)
        with patch('app.payments.upload_payment_proof', return_value='private/two.jpg'):
            self.assertEqual(self.report(image=(io.BytesIO(b'image'), 'new.jpg')).status_code, 200)
        with self.app.app_context():
            reports = PaymentSubmission.query.order_by(PaymentSubmission.id).all()
            self.assertEqual([r.status for r in reports], ['superseded', 'superseded', 'pending'])
            self.assertEqual([r.image_key for r in reports], ['private/one.jpg', 'private/one.jpg', 'private/two.jpg'])

    def test_denial_requires_reason_notifies_and_resubmission_retains_denial(self):
        self.report()
        self.login('admin')
        self.assertEqual(self.review('deny').status_code, 400)
        with patch('app.notifications.send_notification_message', return_value=True) as notify:
            response = self.review('deny', reason='Receipt shows the wrong destination.')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Receipt shows the wrong destination.', notify.call_args.args[3])
        self.login('member')
        denied = self.detail()
        self.assertFalse(denied['pending'])
        self.assertEqual(denied['latest']['denial_reason'], 'Receipt shows the wrong destination.')
        self.assertEqual(self.report(transaction_id='corrected').status_code, 200)
        self.assertEqual(self.detail()['history'][1]['status'], 'denied')

    def test_denial_delivery_failure_is_reported_and_does_not_undo_decision(self):
        self.report()
        self.login('admin')
        with patch('app.notifications.send_notification_message', return_value=False):
            response = self.review('deny', reason='Please correct the amount.')
        self.assertIn('delivery failed', response.json['message'])
        self.assertEqual(self.detail()['latest']['status'], 'denied')

    def test_approval_protects_against_stale_review_and_locks_report(self):
        self.report()
        stale_revision = self.detail()['revision']
        self.assertEqual(self.report(amount='55').status_code, 200)
        self.login('admin')
        self.assertEqual(self.review('approve', revision=stale_revision).status_code, 409)
        self.assertEqual(self.review('approve').status_code, 200)
        self.assertEqual(self.review('deny', reason='late').status_code, 409)
        self.assertTrue(self.detail()['paid'])
        self.login('member')
        self.assertFalse(self.detail()['can_report'])
        self.assertEqual(self.report().status_code, 409)
        with self.app.app_context():
            db.session.get(GroupTest, self.test_id).status = 'closed'
            db.session.commit()
        # Authorization passes, with storage unavailable in this fixture.
        self.assertEqual(self.client.get(f'/result-image/group-test/{self.test_id}').status_code, 503)

    def test_two_sessions_cannot_overwrite_payment_state(self):
        with self.app.app_context(), Session(db.engine) as one, Session(db.engine) as two:
            first = one.get(Participation, self.part_id)
            second = two.get(Participation, self.part_id)
            first.amount_paid = 25
            one.commit()
            second.paid_lab = True
            with self.assertRaises(StaleDataError):
                two.commit()

    def test_owner_admin_permissions_and_proof_access(self):
        with patch('app.payments.upload_payment_proof', return_value='private/receipt.jpg'):
            self.report(image=(io.BytesIO(b'image'), 'receipt.jpg'))
        url = self.detail()['latest']['image_url']
        with patch('app.payments.read_payment_proof', return_value=b'jpeg'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.review('approve').status_code, 403)
        self.login('outsider')
        self.assertEqual(self.client.get(f'/payments/{self.part_id}').status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(f'/payments/{self.part_id}/report').status_code, 403)
        self.login('admin')
        with patch('app.payments.read_payment_proof', return_value=b'jpeg'):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(f'/payments/{self.part_id}/report').status_code, 403)

    def test_order_status_cannot_clear_or_modify_payment(self):
        self.report()
        response = self.client.post(f'/test/{self.test_id}/my-status', data={
            'order_status': 'received_from_vendor', 'amount_paid': '100', 'preferred_payment_option_id': '0',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.detail()['pending'])
        self.assertEqual(self.detail()['latest']['amount'], '50.00')
        self.assertEqual(self.detail()['amount_paid'], '50.00')

    def test_method_snapshot_survives_admin_changes_and_inactive_method(self):
        self.report()
        with self.app.app_context():
            option = db.session.get(PaymentOption, self.option_id)
            option.network = 'Ethereum'
            option.wallet_address = 'changed-wallet'
            option.proof_requirement = 'all'
            db.session.commit()
        # Updating an existing report must not silently change its destination,
        # explorer, or proof policy, even while the option remains active.
        self.assertEqual(self.report(amount='51').status_code, 200)
        self.assertEqual(self.detail()['latest']['method']['network'], 'Base')
        with self.app.app_context():
            option = db.session.get(PaymentOption, self.option_id)
            option.is_active = False
            db.session.commit()
        self.assertEqual(self.detail()['latest']['method']['network'], 'Base')
        self.assertEqual(self.report(amount='52').status_code, 200)
        self.assertEqual(self.detail()['latest']['method']['network'], 'Base')

    def test_admin_can_configure_proof_policy_and_invalid_policy_is_rejected(self):
        self.login('admin')
        payload = {'label': 'Bank transfer', 'method_type': 'other', 'account_handle': 'collector',
                   'proof_image_enabled': 'y', 'proof_transaction_enabled': 'y', 'proof_requirement': 'all'}
        self.assertEqual(self.client.post('/admin/payment-options', data=payload).status_code, 302)
        with self.app.app_context():
            option = PaymentOption.query.filter_by(label='Bank transfer').one()
            self.assertTrue(option.proof_image_enabled)
            self.assertTrue(option.proof_transaction_enabled)
            self.assertEqual(option.proof_requirement, 'all')
        payload.pop('proof_image_enabled')
        payload.pop('proof_transaction_enabled')
        payload['label'] = 'Invalid policy'
        response = self.client.post('/admin/payment-options', data=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Enable at least one proof type', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(PaymentOption.query.filter_by(label='Invalid policy').first())

    def test_upload_failure_preserves_existing_report(self):
        self.report()
        with patch('app.payments.upload_payment_proof', side_effect=StorageUploadError('Upload failed')):
            response = self.report(image=(io.BytesIO(b'bad'), 'receipt.jpg'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.detail()['history']), 1)

    def test_unassigned_method_and_missing_revision_rejected(self):
        self.assertEqual(self.report(option_id='9999').status_code, 400)
        self.assertEqual(self.report(revision='').status_code, 409)

    def test_managed_tenant_write_restrictions_apply_to_payment_endpoints(self):
        payload = {'revision': self.detail()['revision'], 'option_id': self.option_id,
                   'amount': '50', 'transaction_id': 'tx123'}
        with patch('app.routes.subscription_is_readonly', return_value=True):
            self.assertEqual(self.client.post(f'/payments/{self.part_id}/report', data=payload).status_code, 302)
        with patch('app.routes.subscription_access_allowed', return_value=False):
            self.assertEqual(self.client.post(f'/payments/{self.part_id}/report', data=payload).status_code, 302)
        self.assertIsNone(self.detail()['latest'])
        self.report()
        self.login('admin')
        with patch('app.routes.subscription_is_readonly', return_value=True):
            self.assertEqual(self.review('approve').status_code, 302)
        self.assertFalse(self.detail()['paid'])

    def test_csrf_is_required_and_pages_offer_modal_buttons(self):
        page = self.client.get(f'/test/{self.test_id}').get_data(as_text=True)
        self.assertIn('Report Payment', page)
        self.assertIn('modal-fullscreen-sm-down', page)
        self.report()
        self.assertIn('Update Payment', self.client.get(f'/test/{self.test_id}').get_data(as_text=True))
        self.login('admin')
        self.assertIn('View Proof', self.client.get('/admin/action-queue').get_data(as_text=True))
        self.assertIn('Review Payment', self.client.get(f'/admin/manage-participants/{self.test_id}').get_data(as_text=True))
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.assertEqual(self.client.post(f'/payments/{self.part_id}/review', data={'decision': 'approve'}).status_code, 400)

    def test_explorer_mapping_is_chain_specific_and_never_uses_user_urls(self):
        for chain, host in [('BTC', 'mempool.space'), ('ETH', 'etherscan.io'), ('ERC-20', 'etherscan.io'),
                            ('Arbitrum', 'arbiscan.io'), ('Optimism', 'optimistic.etherscan.io'),
                            ('Base', 'basescan.org'), ('Polygon', 'polygonscan.com'), ('SOL', 'solscan.io'),
                            ('TRX', 'tronscan.org'), ('BNB Smart Chain', 'bscscan.com'),
                            ('BCH', 'blockchair.com'), ('LTC', 'litecoinspace.org')]:
            self.assertIn(host, explorer_url(chain, 'AbC123'))
            self.assertTrue(explorer_url(chain, 'AbC123').endswith('AbC123'))
        self.assertIsNone(explorer_url('BNB', 'abc'))
        self.assertIsNone(explorer_url('unknown', 'abc'))
        self.assertIsNone(explorer_url('Ethereum', 'https://evil.test/tx'))

    def test_private_storage_strips_metadata_and_ignores_public_result_settings(self):
        from tests.test_storage import _FakeS3Client
        with self.app.app_context():
            for key, value in {'storage_enabled': 'true', 'storage_bucket': 'public-results',
                               'storage_access_key_id': 'abc', 'storage_secret_access_key': 'xyz',
                               'storage_make_public': 'true'}.items():
                db.session.add(NotificationConfig(key=key, value=value))
            db.session.commit()
            source = io.BytesIO()
            Image.new('RGB', (20, 20), 'blue').save(source, format='PNG')
            source.seek(0)
            fake = _FakeS3Client()
            with patch('app.storage._build_client', return_value=fake):
                key = upload_payment_proof(FileStorage(stream=source, filename='receipt.png'))
            self.assertTrue(key.startswith('payment-proofs/'))
            uploaded = fake.calls[0]
            self.assertEqual(uploaded['Bucket'], 'public-results')
            self.assertNotIn('ACL', uploaded)
            self.assertEqual(uploaded['CacheControl'], 'private, no-store')
            self.assertEqual(uploaded['ContentType'], 'image/jpeg')
            with Image.open(io.BytesIO(uploaded['Body'])) as normalized:
                self.assertFalse(normalized.getexif())
            with self.assertRaises(StorageUploadError):
                upload_payment_proof(FileStorage(stream=io.BytesIO(b'%PDF-fake'), filename='fake.png'))


class PaymentProofMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_legacy_claims_and_defaults_proof_to_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(directory) / 'migration.db')})
            with app.app_context():
                try:
                    upgrade(directory='migrations', revision='d9f3a6c8e2b4')
                    db.session.execute(text("INSERT INTO payment_options (label, method_type, is_active, created_at, updated_at) VALUES ('Legacy', 'other', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
                    db.session.commit()
                    upgrade(directory='migrations')
                    option = PaymentOption.query.one()
                    self.assertFalse(option.proof_image_enabled)
                    self.assertFalse(option.proof_transaction_enabled)
                    self.assertEqual(option.proof_requirement, 'optional')
                    self.assertIn('payment_submissions', inspect(db.engine).get_table_names())
                    self.assertEqual(PaymentSubmission.query.count(), 0)
                    db.session.remove()
                    downgrade(directory='migrations', revision='d9f3a6c8e2b4')
                    self.assertNotIn('payment_submissions', inspect(db.engine).get_table_names())
                    self.assertEqual(db.session.execute(text('SELECT label FROM payment_options')).scalar_one(), 'Legacy')
                finally:
                    db.session.remove()
                    db.engine.dispose()
