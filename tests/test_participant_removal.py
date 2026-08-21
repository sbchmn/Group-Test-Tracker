import tempfile
import unittest
from pathlib import Path

from app import create_app, db
from app.models import GroupTest, Participation, User


class ParticipantRemovalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def test_admin_can_remove_participant_from_test(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Sample Test", created_by=1)
            db.session.add_all([admin, member, test])
            db.session.commit()

            part = Participation(group_test_id=test.id, user_id=member.id, name=member.username, approved=False)
            db.session.add(part)
            db.session.commit()
            part_id = part.id

        login_response = self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )
        self.assertEqual(login_response.status_code, 200)

        remove_response = self.client.post(f"/admin/remove-participant/{part_id}", follow_redirects=True)
        self.assertEqual(remove_response.status_code, 200)

        with self.app.app_context():
            self.assertIsNone(Participation.query.get(part_id))

    def test_action_queue_bulk_approval_recalculates_affected_tests(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member_one = User(username="member1", email="member1@example.com", is_admin=False, is_active=True)
            member_one.set_password("password")
            member_two = User(username="member2", email="member2@example.com", is_admin=False, is_active=True)
            member_two.set_password("password")
            member_three = User(username="member3", email="member3@example.com", is_admin=False, is_active=True)
            member_three.set_password("password")
            test_one = GroupTest(title="Test One", created_by=1, total_lab_cost=100.0)
            test_two = GroupTest(title="Test Two", created_by=1, total_lab_cost=60.0)
            db.session.add_all([admin, member_one, member_two, member_three, test_one, test_two])
            db.session.commit()

            already_approved = Participation(
                group_test_id=test_one.id,
                user_id=member_one.id,
                name=member_one.username,
                approved=True,
                amount_owed=100.0,
            )
            pending_one = Participation(
                group_test_id=test_one.id,
                user_id=member_two.id,
                name=member_two.username,
                approved=False,
            )
            pending_two = Participation(
                group_test_id=test_two.id,
                user_id=member_three.id,
                name=member_three.username,
                approved=False,
            )
            db.session.add_all([already_approved, pending_one, pending_two])
            db.session.commit()

            pending_one_id = pending_one.id
            pending_two_id = pending_two.id
            already_approved_id = already_approved.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/action-queue/approve-selected",
            data={"part_ids": [str(pending_one_id), str(pending_two_id)]},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            refreshed_pending_one = Participation.query.get(pending_one_id)
            refreshed_pending_two = Participation.query.get(pending_two_id)
            refreshed_existing = Participation.query.get(already_approved_id)

            self.assertTrue(refreshed_pending_one.approved)
            self.assertIsNotNone(refreshed_pending_one.approved_at)
            self.assertTrue(refreshed_pending_two.approved)
            self.assertIsNotNone(refreshed_pending_two.approved_at)

            # Test One now has two approved members, so fair share should be split.
            self.assertAlmostEqual(refreshed_pending_one.amount_owed, 50.0, places=2)
            self.assertAlmostEqual(refreshed_existing.amount_owed, 50.0, places=2)
            # Test Two has one approved member and a $60 lab total.
            self.assertAlmostEqual(refreshed_pending_two.amount_owed, 60.0, places=2)

    def test_action_queue_deny_selected_removes_pending_requests(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member_one = User(username="member1", email="member1@example.com", is_admin=False, is_active=True)
            member_one.set_password("password")
            member_two = User(username="member2", email="member2@example.com", is_admin=False, is_active=True)
            member_two.set_password("password")
            test = GroupTest(title="Deny Test", created_by=1)
            db.session.add_all([admin, member_one, member_two, test])
            db.session.commit()

            pending_one = Participation(group_test_id=test.id, user_id=member_one.id, name=member_one.username, approved=False)
            pending_two = Participation(group_test_id=test.id, user_id=member_two.id, name=member_two.username, approved=False)
            db.session.add_all([pending_one, pending_two])
            db.session.commit()

            pending_one_id = pending_one.id
            pending_two_id = pending_two.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/action-queue/deny-selected",
            data={"part_ids": [str(pending_one_id), str(pending_two_id)]},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            self.assertIsNone(Participation.query.get(pending_one_id))
            self.assertIsNone(Participation.query.get(pending_two_id))

    def test_action_queue_approve_filtered_requires_confirmation_text(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member_one = User(username="member1", email="member1@example.com", is_admin=False, is_active=True)
            member_one.set_password("password")
            member_two = User(username="member2", email="member2@example.com", is_admin=False, is_active=True)
            member_two.set_password("password")
            test = GroupTest(title="Alpha Search Match", compound="Alpha", created_by=1, total_lab_cost=90.0)
            db.session.add_all([admin, member_one, member_two, test])
            db.session.commit()

            pending_one = Participation(group_test_id=test.id, user_id=member_one.id, name=member_one.username, approved=False)
            pending_two = Participation(group_test_id=test.id, user_id=member_two.id, name=member_two.username, approved=False)
            db.session.add_all([pending_one, pending_two])
            db.session.commit()

            pending_one_id = pending_one.id
            pending_two_id = pending_two.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        invalid_response = self.client.post(
            "/admin/action-queue/approve-filtered",
            data={"status": "all", "q": "Alpha", "confirm_text": "NOPE"},
            follow_redirects=True,
        )
        self.assertEqual(invalid_response.status_code, 200)

        with self.app.app_context():
            self.assertFalse(Participation.query.get(pending_one_id).approved)
            self.assertFalse(Participation.query.get(pending_two_id).approved)

        valid_response = self.client.post(
            "/admin/action-queue/approve-filtered",
            data={"status": "all", "q": "Alpha", "confirm_text": "APPROVE FILTERED"},
            follow_redirects=True,
        )
        self.assertEqual(valid_response.status_code, 200)

        with self.app.app_context():
            refreshed_one = Participation.query.get(pending_one_id)
            refreshed_two = Participation.query.get(pending_two_id)
            self.assertTrue(refreshed_one.approved)
            self.assertTrue(refreshed_two.approved)
            # Two approved participants on a $90 test => $45 each.
            self.assertAlmostEqual(refreshed_one.amount_owed, 45.0, places=2)
            self.assertAlmostEqual(refreshed_two.amount_owed, 45.0, places=2)

    def test_action_queue_pagination_splits_large_pending_list(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            test = GroupTest(title="Pagination Test", created_by=1)
            db.session.add_all([admin, test])
            db.session.commit()

            for idx in range(30):
                member = User(username=f"member{idx}", email=f"member{idx}@example.com", is_admin=False, is_active=True)
                member.set_password("password")
                db.session.add(member)
                db.session.flush()
                part = Participation(group_test_id=test.id, user_id=member.id, name=member.username, approved=False)
                db.session.add(part)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        page_one = self.client.get("/admin/action-queue?page=1", follow_redirects=True)
        self.assertEqual(page_one.status_code, 200)
        self.assertIn(b"member0", page_one.data)
        self.assertNotIn(b"member29", page_one.data)

        page_two = self.client.get("/admin/action-queue?page=2", follow_redirects=True)
        self.assertEqual(page_two.status_code, 200)
        self.assertIn(b"member29", page_two.data)


if __name__ == "__main__":
    unittest.main()
