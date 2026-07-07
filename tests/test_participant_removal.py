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


if __name__ == "__main__":
    unittest.main()
