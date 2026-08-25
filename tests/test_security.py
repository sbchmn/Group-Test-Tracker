import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import GroupTest, Participation, PublicResult, User


class SecurityTests(unittest.TestCase):
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

    def test_create_user_does_not_flash_generated_password(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/users/new",
            data={
                "username": "newuser",
                "email": "new@example.com",
                "password": "",
                "is_admin": False,
                "is_active": True,
                "receive_group_test_notifications": True,
                "notification_channel": "email",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Temporary password generated", response.get_data(as_text=True))

    def test_create_app_requires_secret_key_outside_test_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                create_app()

    def test_group_test_result_image_requires_paid_participant(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            viewer = User(username="viewer", email="viewer@example.com", is_admin=False)
            viewer.set_password("secret")
            db.session.add_all([admin, viewer])
            db.session.flush()

            test = GroupTest(
                title="Secure Result Test",
                status="closed",
                results_link="https://example.com/result",
                results_image_key="result-images/group-tests/secure.jpg",
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            part = Participation(
                group_test_id=test.id,
                user_id=viewer.id,
                approved=True,
                paid_lab=False,
                denied=False,
                name="Viewer",
            )
            db.session.add(part)
            db.session.commit()

            test_id = test.id
            part_id = part.id

        self.client.post("/login", data={"username": "viewer", "password": "secret"}, follow_redirects=True)

        response = self.client.get(f"/result-image/group-test/{test_id}", follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        with self.app.app_context():
            part = Participation.query.get(part_id)
            part.paid_lab = True
            db.session.commit()

        with patch("app.routes.generate_result_image_presigned_url", return_value="https://signed.example.com/image"):
            response = self.client.get(f"/result-image/group-test/{test_id}", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "https://signed.example.com/image")

    def test_public_result_image_requires_login(self):
        with self.app.app_context():
            db.create_all()

            admin = User(username="admin", email="admin@example.com", is_admin=True)
            admin.set_password("secret")
            db.session.add(admin)
            db.session.flush()

            public_result = PublicResult(
                title="Public Result",
                summary="Summary",
                results_link="https://example.com/result",
                results_image_key="result-images/public-results/secure.jpg",
                created_by=admin.id,
            )
            db.session.add(public_result)
            db.session.commit()
            public_result_id = public_result.id

        anonymous_response = self.client.get(f"/result-image/public/{public_result_id}", follow_redirects=False)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/login", anonymous_response.headers.get("Location", ""))

        self.client.post("/login", data={"username": "admin", "password": "secret"}, follow_redirects=True)
        with patch("app.routes.generate_result_image_presigned_url", return_value="https://signed.example.com/public-image"):
            authed_response = self.client.get(f"/result-image/public/{public_result_id}", follow_redirects=False)

        self.assertEqual(authed_response.status_code, 302)
        self.assertEqual(authed_response.headers.get("Location"), "https://signed.example.com/public-image")
