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

    def test_action_queue_deny_selected_marks_denied_with_reason(self):
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
            data={
                "part_ids": [str(pending_one_id), str(pending_two_id)],
                "deny_reason": "Insufficient verification",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            denied_one = Participation.query.get(pending_one_id)
            denied_two = Participation.query.get(pending_two_id)
            self.assertIsNotNone(denied_one)
            self.assertIsNotNone(denied_two)
            self.assertTrue(denied_one.denied)
            self.assertTrue(denied_two.denied)
            self.assertEqual(denied_one.denied_reason, "Insufficient verification")
            self.assertEqual(denied_two.denied_reason, "Insufficient verification")

    def test_queue_denial_visible_on_manage_participants_page(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Visibility Test", created_by=1)
            db.session.add_all([admin, member, test])
            db.session.commit()

            pending = Participation(group_test_id=test.id, user_id=member.id, name=member.username, approved=False)
            db.session.add(pending)
            db.session.commit()
            pending_id = pending.id
            test_id = test.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        deny_response = self.client.post(
            f"/admin/action-queue/deny/{pending_id}",
            data={"deny_reason": "Missing profile details"},
            follow_redirects=True,
        )
        self.assertEqual(deny_response.status_code, 200)

        manage_response = self.client.get(
            f"/admin/manage-participants/{test_id}",
            follow_redirects=True,
        )
        self.assertEqual(manage_response.status_code, 200)
        body = manage_response.get_data(as_text=True)
        self.assertIn("Denied", body)
        self.assertIn("Missing profile details", body)

    def test_manage_participants_can_deny_and_reopen_request(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Manage Actions Test", created_by=1)
            db.session.add_all([admin, member, test])
            db.session.commit()

            pending = Participation(group_test_id=test.id, user_id=member.id, name=member.username, approved=False)
            db.session.add(pending)
            db.session.commit()
            pending_id = pending.id
            test_id = test.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        deny_response = self.client.post(
            f"/admin/manage-participants/{test_id}/deny/{pending_id}",
            data={"deny_reason": "Not enough information"},
            follow_redirects=True,
        )
        self.assertEqual(deny_response.status_code, 200)

        with self.app.app_context():
            denied = Participation.query.get(pending_id)
            self.assertTrue(denied.denied)
            self.assertEqual(denied.denied_reason, "Not enough information")

        reopen_response = self.client.post(
            f"/admin/manage-participants/{test_id}/reopen/{pending_id}",
            follow_redirects=True,
        )
        self.assertEqual(reopen_response.status_code, 200)

        with self.app.app_context():
            reopened = Participation.query.get(pending_id)
            self.assertFalse(reopened.denied)
            self.assertIsNone(reopened.denied_reason)
            self.assertFalse(reopened.approved)

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

    def test_dashboard_quick_request_creates_pending_and_blocks_duplicate(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Recruiting Test", created_by=1, status="recruiting")
            db.session.add_all([admin, member, test])
            db.session.commit()
            test_id = test.id
            member_id = member.id

        self.client.post(
            "/login",
            data={"username": "member", "password": "password"},
            follow_redirects=True,
        )

        first_response = self.client.post(
            f"/test/{test_id}/request-quick",
            follow_redirects=True,
        )
        self.assertEqual(first_response.status_code, 200)

        with self.app.app_context():
            requests = Participation.query.filter_by(group_test_id=test_id, user_id=member_id).all()
            self.assertEqual(len(requests), 1)
            self.assertFalse(requests[0].approved)

        dashboard_after_request = self.client.get("/dashboard", follow_redirects=True)
        self.assertEqual(dashboard_after_request.status_code, 200)
        self.assertNotIn("Request Join", dashboard_after_request.get_data(as_text=True))

        second_response = self.client.post(
            f"/test/{test_id}/request-quick",
            follow_redirects=True,
        )
        self.assertEqual(second_response.status_code, 200)

        with self.app.app_context():
            requests = Participation.query.filter_by(group_test_id=test_id, user_id=member_id).all()
            self.assertEqual(len(requests), 1)

    def test_dashboard_group_by_join_state_shows_pending_approved_not_joined(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test_pending = GroupTest(title="Pending Test", created_by=1, status="recruiting")
            test_approved = GroupTest(title="Approved Test", created_by=1, status="recruiting")
            test_not_joined = GroupTest(title="Not Joined Test", created_by=1, status="recruiting")
            db.session.add_all([admin, member, test_pending, test_approved, test_not_joined])
            db.session.commit()

            pending_part = Participation(
                group_test_id=test_pending.id,
                user_id=member.id,
                name=member.username,
                approved=False,
            )
            approved_part = Participation(
                group_test_id=test_approved.id,
                user_id=member.id,
                name=member.username,
                approved=True,
            )
            db.session.add_all([pending_part, approved_part])
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "member", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.get("/dashboard?group_by=join_state&sort_by=title", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Approved", body)
        self.assertIn("Pending", body)
        self.assertIn("Not Joined", body)
        self.assertNotIn("Join Request Pending", body)

    def test_group_test_detail_shows_denied_status_and_reason(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Denied Detail Test", created_by=1, status="recruiting")
            db.session.add_all([admin, member, test])
            db.session.commit()

            denied_part = Participation(
                group_test_id=test.id,
                user_id=member.id,
                name=member.username,
                approved=False,
                denied=True,
                denied_reason="Missing required identity verification",
            )
            db.session.add(denied_part)
            db.session.commit()
            test_id = test.id

        self.client.post(
            "/login",
            data={"username": "member", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.get(f"/test/{test_id}", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Your join request was denied.", body)
        self.assertIn("Missing required identity verification", body)
        self.assertNotIn("Pending Admin Review", body)
        self.assertNotIn("<strong>Participants</strong>", body)

    def test_denied_user_can_reapply_and_reset_denial_state(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Reapply Test", created_by=1, status="recruiting")
            db.session.add_all([admin, member, test])
            db.session.commit()

            denied_part = Participation(
                group_test_id=test.id,
                user_id=member.id,
                name=member.username,
                approved=False,
                denied=True,
                denied_reason="Prior issue",
            )
            db.session.add(denied_part)
            db.session.commit()
            part_id = denied_part.id
            test_id = test.id

        self.client.post(
            "/login",
            data={"username": "member", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.post(
            f"/test/{test_id}/reapply",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            refreshed = Participation.query.get(part_id)
            self.assertFalse(refreshed.denied)
            self.assertIsNone(refreshed.denied_at)
            self.assertIsNone(refreshed.denied_reason)
            self.assertFalse(refreshed.approved)

    def test_admin_add_participant_can_reactivate_denied_user(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            member = User(username="member", email="member@example.com", is_admin=False, is_active=True)
            member.set_password("password")
            test = GroupTest(title="Manual Add After Denial", created_by=1, status="recruiting", total_lab_cost=80.0)
            db.session.add_all([admin, member, test])
            db.session.commit()

            denied_part = Participation(
                group_test_id=test.id,
                user_id=member.id,
                name=member.username,
                approved=False,
                denied=True,
                denied_reason="Docs missing",
            )
            db.session.add(denied_part)
            db.session.commit()
            test_id = test.id
            member_id = member.id
            part_id = denied_part.id

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        add_response = self.client.post(
            f"/admin/add-participant/{test_id}",
            data={"user_id": member_id},
            follow_redirects=True,
        )
        self.assertEqual(add_response.status_code, 200)

        with self.app.app_context():
            parts = Participation.query.filter_by(group_test_id=test_id, user_id=member_id).all()
            self.assertEqual(len(parts), 1)
            part = Participation.query.get(part_id)
            self.assertTrue(part.approved)
            self.assertFalse(part.denied)
            self.assertIsNone(part.denied_reason)


if __name__ == "__main__":
    unittest.main()
