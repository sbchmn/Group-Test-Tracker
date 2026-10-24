import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from flask_migrate import upgrade, downgrade
from sqlalchemy import text
from sqlalchemy.orm.exc import StaleDataError

from app import create_app, db, costs
from app.account_merge import preview
from app.models import (AccountMergeAudit, BotLinkToken, DashboardHiddenGroupTest, GroupTest,
                        Participation, PaymentSubmission, PublicResult, ResultAnalysisRun,
                        User, UserDigestEvent)


class AccountMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(self.tmp.name) / 'merge.db'),
            'NOTIFICATION_LOG_PATH': str(Path(self.tmp.name) / 'notifications.log')})
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            db.session.execute(text('PRAGMA foreign_keys=ON'))
            users = [User(username=name, email=name+'@example.test', is_admin=name=='admin')
                     for name in ['admin','primary','duplicate','other']]
            for user in users: user.set_password('secret123')
            db.session.add_all(users); db.session.flush()
            self.ids = {u.username:u.id for u in users}
            test = GroupTest(title='Shared frozen test', created_by=self.ids['duplicate'],
                total_lab_cost=600, refund_per_donor=0, status='recruiting')
            db.session.add(test); db.session.flush(); self.test_id=test.id
            self.parts={}
            for user in users[1:]:
                p=Participation(user_id=user.id,group_test_id=test.id,approved=True,name=user.username,notes=user.username+' note')
                db.session.add(p);db.session.flush();self.parts[user.username]=p.id
            costs.freeze(test,self.ids['duplicate']); test.status='closed'
            p=db.session.get(Participation,self.parts['primary']);p.amount_owed=100;p.amount_paid=100;p.paid_lab=True
            p.payment_verified_by_id=self.ids['duplicate'];p.payment_verified_at=datetime.utcnow()
            d=db.session.get(Participation,self.parts['duplicate']);d.amount_owed=120;d.amount_paid=25;d.payment_claimed_at=datetime.utcnow()
            for part,amount,status in [(p,100,'approved'),(d,25,'pending')]:
                db.session.add(PaymentSubmission(participation=part,amount=amount,status=status,
                    method_snapshot={'title':'Bank transfer'},transaction_id=part.name+'-tx',image_key=part.name+'.jpg',reviewed_by_id=self.ids['duplicate']))
            db.session.commit()
        self.login('admin')

    def tearDown(self):
        with self.app.app_context(): db.session.remove();db.engine.dispose()
        self.tmp.cleanup()

    def login(self,name,client=None):
        client=client or self.client
        client.get('/logout');client.post('/login',data={'username':name,'password':'secret123'})

    def payload(self,**overrides):
        with self.app.app_context():
            plan=preview(db.session.get(User,self.ids['primary']),db.session.get(User,self.ids['duplicate']),self.ids['admin'])
        values={'primary_id':self.ids['primary'],'duplicate_id':self.ids['duplicate'],
            'preview_token':plan['token'],'confirm_merge':'yes',
            'membership_'+str(self.test_id):'primary','charge_'+str(self.test_id):'primary',
            'payment_'+str(self.test_id):'primary'}
        values.update(overrides);return values

    def merge(self,**overrides):
        return self.client.post('/admin/users/merge',data=self.payload(**overrides),follow_redirects=True)

    def test_frozen_merge_keeps_charges_proofs_notes_and_selected_current_report(self):
        response=self.merge()
        self.assertIn('Accounts merged',response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(db.session.get(User,self.ids['duplicate']))
            p=db.session.get(Participation,self.parts['primary'])
            self.assertEqual((p.amount_owed,p.amount_paid,p.paid_lab),(100,100,True))
            self.assertEqual(p.current_payment_submission.transaction_id,'primary-tx')
            self.assertEqual(len(p.payment_submissions),2)
            self.assertEqual({r.image_key for r in p.payment_submissions},{'primary.jpg','duplicate.jpg'})
            self.assertTrue(next(r for r in p.payment_submissions if r.transaction_id=='duplicate-tx').archived_by_merge)
            self.assertIn('duplicate note',p.notes)
            self.assertEqual(db.session.get(Participation,self.parts['other']).amount_owed,200)
            self.assertEqual(p.payment_verified_by_id,self.ids['primary'])
            audit=AccountMergeAudit.query.one()
            self.assertEqual(audit.performed_by_id,self.ids['admin'])
            self.assertEqual(len(audit.details['participations_before']),2)
            self.assertNotIn('password_hash',str(audit.details))
            self.assertEqual(db.session.get(GroupTest,self.test_id).created_by,self.ids['primary'])
        detail=self.client.get('/payments/'+str(self.parts['primary'])).json
        self.assertEqual(detail['latest']['transaction_id'],'primary-tx')
        self.assertEqual(len(detail['history']),2)

    def test_explicit_overlap_choices_keep_duplicate_payment_and_charge(self):
        self.merge(**{'payment_'+str(self.test_id):'duplicate','charge_'+str(self.test_id):'duplicate'})
        detail=self.client.get('/payments/'+str(self.parts['primary'])).json
        self.assertEqual(detail['amount_owed'],'120.00');self.assertEqual(detail['amount_paid'],'25.00')
        self.assertFalse(detail['paid']);self.assertTrue(detail['pending'])
        self.assertEqual(detail['latest']['transaction_id'],'duplicate-tx')
        response=self.client.post('/payments/'+str(self.parts['primary'])+'/review',data={'revision':detail['revision'],'decision':'approve'})
        self.assertEqual(response.status_code,200)
        with self.app.app_context():
            p=db.session.get(Participation,self.parts['primary'])
            self.assertTrue(p.paid_lab)
            self.assertEqual(p.current_payment_submission.status,'approved')

    def test_unique_records_all_user_references_hidden_tests_and_digests_transfer(self):
        with self.app.app_context():
            extra=GroupTest(title='Unique test',created_by=self.ids['duplicate'],status='closed')
            db.session.add(extra);db.session.flush();extra_id=extra.id
            db.session.add(Participation(group_test_id=extra.id,user_id=self.ids['duplicate'],approved=True,amount_owed=75))
            db.session.add(PublicResult(title='Result',created_by=self.ids['duplicate']))
            db.session.add(ResultAnalysisRun(group_test_id=extra.id,source_kind='upload',source_reference='test.jpg',provider='openai',provider_model='fixture-model',status='queued',requested_by_id=self.ids['duplicate'],reviewed_by_id=self.ids['duplicate']))
            for user_id in [self.ids['primary'],self.ids['duplicate']]:
                db.session.add(DashboardHiddenGroupTest(user_id=user_id,group_test_id=extra.id))
                db.session.add(UserDigestEvent(user_id=user_id,test_id=extra.id,test_title=extra.title,old_status='testing',new_status='closed'))
                db.session.add(BotLinkToken(user_id=user_id,provider='telegram',token=str(user_id),expires_at=datetime.utcnow()+timedelta(hours=1)))
            db.session.commit()
        self.merge()
        with self.app.app_context():
            p=Participation.query.filter_by(group_test_id=extra_id).one()
            self.assertEqual((p.user_id,p.amount_owed),(self.ids['primary'],75))
            self.assertEqual(DashboardHiddenGroupTest.query.count(),1)
            self.assertEqual(UserDigestEvent.query.count(),1)
            self.assertEqual(BotLinkToken.query.count(),0)
            self.assertEqual(PublicResult.query.one().created_by,self.ids['primary'])
            self.assertEqual(ResultAnalysisRun.query.one().reviewed_by_id,self.ids['primary'])
            self.assertEqual(db.session.execute(text('PRAGMA foreign_key_check')).all(),[])

    def test_recruiting_merge_recalculates_funding_pool_quietly(self):
        with self.app.app_context():
            test=db.session.get(GroupTest,self.test_id);test.status='recruiting';test.costs_frozen=False;test.cost_snapshot=None
            db.session.commit()
        with patch('app.routes.send_notification_message') as send:
            self.merge()
        send.assert_not_called()
        with self.app.app_context():
            self.assertEqual([p.amount_owed for p in Participation.query.all()],[300,300])

    def test_conflicting_links_require_choice_and_unique_id_can_transfer(self):
        with self.app.app_context():
            p=db.session.get(User,self.ids['primary']);d=db.session.get(User,self.ids['duplicate'])
            p.telegram_user_id='111';p.telegram_chat_id='111';d.telegram_user_id='222';d.telegram_chat_id='222'
            p.discord_user_id='333';d.discord_user_id='444';d.root_user_id='root-duplicate'
            db.session.commit()
        response=self.merge()
        self.assertIn('Resolve each conflicting',response.get_data(as_text=True))
        self.merge(link_telegram='duplicate',link_discord='primary')
        with self.app.app_context():
            p=db.session.get(User,self.ids['primary'])
            self.assertEqual((p.telegram_user_id,p.telegram_chat_id,p.discord_user_id,p.root_user_id),('222','222','333','root-duplicate'))
            self.assertTrue(p.check_password('secret123'));self.assertFalse(p.is_admin)

    def test_missing_choices_or_confirmation_do_not_merge(self):
        for overrides in [{'membership_'+str(self.test_id):''},{'payment_'+str(self.test_id):''},{'charge_'+str(self.test_id):''},{'confirm_merge':''}]:
            self.merge(**overrides)
            with self.app.app_context(): self.assertIsNotNone(db.session.get(User,self.ids['duplicate']))
        # A failure after moving proofs must roll back the entire transaction.
        with patch('app.account_merge.costs.recalculate', side_effect=StaleDataError('concurrent write')):
            self.merge()
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(User,self.ids['duplicate']))
            self.assertEqual(AccountMergeAudit.query.count(),0)
            self.assertEqual(PaymentSubmission.query.filter_by(archived_by_merge=True).count(),0)
            self.assertEqual({r.participation_id for r in PaymentSubmission.query.all()},
                             {self.parts['primary'],self.parts['duplicate']})

    def test_changed_proof_or_account_invalidates_preview(self):
        for field in ['proof','account']:
            data=self.payload()
            with self.app.app_context():
                if field=='proof': PaymentSubmission.query.first().transaction_id='changed-tx'
                else: db.session.get(User,self.ids['primary']).email='changed@example.test'
                db.session.commit()
            response=self.client.post('/admin/users/merge',data=data,follow_redirects=True)
            self.assertIn('fresh preview',response.get_data(as_text=True))
            with self.app.app_context():self.assertEqual(AccountMergeAudit.query.count(),0)

    def test_sessions_for_both_accounts_and_legacy_sessions_are_invalidated(self):
        primary_client=self.app.test_client();duplicate_client=self.app.test_client()
        self.login('primary',primary_client);self.login('duplicate',duplicate_client)
        legacy=self.app.test_client()
        with legacy.session_transaction() as session: session['_user_id']=str(self.ids['primary']);session['_fresh']=True
        self.merge()
        for client in [primary_client,duplicate_client,legacy]:
            self.assertEqual(client.get('/profile').status_code,302)
        self.login('primary',primary_client)
        self.assertEqual(primary_client.get('/profile').status_code,200)

    def test_cannot_merge_system_identity_self_or_last_admin_away(self):
        with self.app.app_context():
            p=db.session.get(User,self.ids['primary']);d=db.session.get(User,self.ids['duplicate'])
            for first,second,actor in [(p,p,self.ids['admin']),(p,d,d.id)]:
                with self.assertRaises(ValueError):preview(first,second,actor)
            d.system_account_key='control_plane_support'
            with self.assertRaises(ValueError):preview(p,d,self.ids['admin'])
            db.session.rollback()
            admin=db.session.get(User,self.ids['admin'])
            with self.assertRaises(ValueError):preview(p,admin,self.ids['other'])

    def test_ordinary_user_cannot_preview_or_submit_and_csrf_is_enforced(self):
        data=self.payload();self.login('primary')
        self.assertNotEqual(self.client.get('/admin/users/merge').status_code,200)
        self.client.post('/admin/users/merge',data=data)
        with self.app.app_context():self.assertEqual(AccountMergeAudit.query.count(),0)
        self.login('admin');self.app.config['WTF_CSRF_ENABLED']=True
        self.assertEqual(self.client.post('/admin/users/merge',data=data).status_code,400)

    def test_deleted_highest_account_id_is_not_reused(self):
        with self.app.app_context():
            d=User(username='last-user',email='last@example.test',password_hash='hash');db.session.add(d);db.session.commit();ident=d.id
            data=preview(db.session.get(User,self.ids['primary']),d,self.ids['admin'])
        self.client.post('/admin/users/merge',data={'primary_id':self.ids['primary'],'duplicate_id':ident,'preview_token':data['token'],'confirm_merge':'yes'})
        with self.app.app_context():
            new=User(username='new-user',email='new@example.test',password_hash='hash');db.session.add(new);db.session.commit()
            self.assertGreater(new.id,ident)


class UsernamePolicyTests(unittest.TestCase):
    def setUp(self):
        self.app=create_app({'TESTING':True,'WTF_CSRF_ENABLED':False,'SQLALCHEMY_DATABASE_URI':'sqlite://','RATELIMIT_ENABLED':False})
        self.ctx=self.app.app_context();self.ctx.push();db.create_all()

    def tearDown(self):
        db.session.remove();db.engine.dispose();self.ctx.pop()

    def test_forms_reject_all_whitespace_without_silently_trimming(self):
        from app.routes import RegisterForm, UserForm, ProfileForm
        from werkzeug.datastructures import MultiDict
        for value in [' name','name ','na me','na\tme','na\nme','na\u00a0me','na\u2003me']:
            for cls in [RegisterForm,UserForm,ProfileForm]:
                form=cls(MultiDict({'username':value}))
                self.assertFalse(form.username.validate(form),(cls,value))
                self.assertIn('whitespace',str(form.username.errors))
        form=RegisterForm(MultiDict({'username':'valid.name-123'}))
        self.assertTrue(form.username.validate(form))

    def test_model_rejects_new_or_changed_names_but_preserves_existing_legacy_names(self):
        user=User(username='bad name',email='bad@example.test',password_hash='hash');db.session.add(user)
        with self.assertRaises(ValueError):db.session.commit()
        db.session.rollback()
        user=User(username='valid',email='valid@example.test',password_hash='hash');db.session.add(user);db.session.commit();ident=user.id
        db.session.execute(text("UPDATE users SET username='old name' WHERE id=:id"),{'id':ident});db.session.commit();db.session.expire_all()
        user=db.session.get(User,ident);user.email='new@example.test';db.session.commit()
        self.assertEqual(user.username,'old name')
        from app.routes import UserForm
        from werkzeug.datastructures import MultiDict
        form=UserForm(MultiDict({'username':'old name'}),obj=user)
        self.assertTrue(form.username.validate(form))
        user.username='another bad name'
        with self.assertRaises(ValueError):db.session.commit()
        db.session.rollback()

    def test_registration_and_cli_show_validation(self):
        client=self.app.test_client()
        response=client.post('/register',data={'username':' invalid ','email':'invalid@example.test','password':'secret123','confirm_password':'secret123'})
        self.assertIn('Usernames cannot contain',response.get_data(as_text=True));self.assertEqual(User.query.count(),0)
        result=self.app.test_cli_runner().invoke(args=['create-admin','--username','bad name','--email','cli@example.test','--password','secret123'])
        self.assertNotEqual(result.exit_code,0);self.assertIn('whitespace',result.output)
        with patch('app.control_plane_routes._verify_control_plane_request', return_value=(({}, b'{}'), None)):
            for path, payload in [('bootstrap', {'username':' leading','support_username':'gtmsupport'}),
                                  ('support', {'username':'gtmsupport ','action':'enable'})]:
                response=client.post('/internal/control-plane/v1/'+path,json=payload)
                self.assertEqual(response.status_code,400)
                self.assertIn('whitespace',response.json['error'])


class AccountMergeMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_users_and_payment_records_and_prevents_sqlite_id_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            app=create_app({'TESTING':True,'SQLALCHEMY_DATABASE_URI':'sqlite:///'+str(Path(directory)/'migration.db')})
            with app.app_context():
                try:
                    upgrade(directory='migrations',revision='a9c3e5f7b2d4')
                    db.session.execute(text("INSERT INTO users (id,username,email,password_hash,is_admin,is_active,session_epoch,created_at) VALUES (9,'legacy name','legacy@example.test','hash',1,1,0,CURRENT_TIMESTAMP)"));db.session.commit()
                    db.session.execute(text("INSERT INTO group_tests (id,title,status,total_lab_cost,shipping_cost,donor_shipping_cost,refund_per_donor,created_by,created_at,updated_at,costs_frozen,cost_revision) VALUES (1,'Legacy test','closed',100,0,0,0,9,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1,1)"))
                    db.session.execute(text("INSERT INTO participations (id,group_test_id,user_id,approved,denied,amount_owed,amount_paid,payment_revision,is_late_buy_in,requested_at) VALUES (1,1,9,1,0,100,80,1,0,CURRENT_TIMESTAMP)"))
                    db.session.execute(text("INSERT INTO payment_submissions (participation_id,amount,method_snapshot,status,image_key,submitted_at) VALUES (1,80,'{}','approved','legacy-proof.jpg',CURRENT_TIMESTAMP)"));db.session.commit()
                    upgrade(directory='migrations')
                    self.assertIn('AUTOINCREMENT',db.session.execute(text("SELECT sql FROM sqlite_master WHERE name='users'")).scalar_one())
                    user=db.session.get(User,9);self.assertEqual(user.username,'legacy name')
                    proof=PaymentSubmission.query.one();self.assertFalse(proof.archived_by_merge)
                    self.assertEqual(proof.image_key,'legacy-proof.jpg')
                    # Remove fixture references before testing SQLite's user-ID allocation.
                    db.session.delete(proof);db.session.delete(Participation.query.one())
                    db.session.delete(db.session.get(GroupTest,1));db.session.flush()
                    db.session.delete(user);db.session.commit()
                    user=User(username='fresh',email='fresh@example.test',password_hash='hash');db.session.add(user);db.session.commit();self.assertGreater(user.id,9)
                    db.session.remove();downgrade(directory='migrations',revision='a9c3e5f7b2d4')
                    self.assertEqual(db.session.execute(text('SELECT username FROM users')).scalar_one(),'fresh')
                finally:db.session.remove();db.engine.dispose()
