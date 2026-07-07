import tempfile
import unittest
from pathlib import Path

from app import create_app, db
from app.models import GroupTest, User


class LabCostTests(unittest.TestCase):
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

    def test_create_test_saves_lab_items_and_lab_name(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin", email="admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            db.session.add(admin)
            db.session.commit()

        self.client.post(
            "/login",
            data={"username": "admin", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/create-test",
            data={
                "title": "Lab Test",
                "status": "recruiting",
                "total_lab_cost": "600",
                "shipping_cost": "25",
                "refund_per_donor": "20",
                "lab_name": "North Lab",
                "lab_item_name": ["MASS", "STERILITY"],
                "lab_item_price": ["360", "240"],
                "lab_item_vials": ["1", "0"],
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            test = GroupTest.query.filter_by(title="Lab Test").first()
            self.assertIsNotNone(test)
            self.assertEqual(test.lab_name, "North Lab")
            self.assertEqual(test.total_lab_cost, 600.0)
            self.assertEqual(test.lab_test_details, [
                {"name": "MASS", "price": 360.0, "vials_needed": 1},
                {"name": "STERILITY", "price": 240.0, "vials_needed": 0},
            ])


if __name__ == "__main__":
    unittest.main()
