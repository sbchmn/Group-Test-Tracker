import tempfile
import unittest
from pathlib import Path

from app import create_app, db
from app.models import GroupTest, Participation, User


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

    def test_create_test_saves_donor_shipping_reimbursement_selection(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="admin2", email="admin2@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            participant = User(username="participant", email="participant@example.com", is_admin=False, is_active=True)
            participant.set_password("password")
            db.session.add_all([admin, participant])
            db.session.commit()
            participant_id = participant.id

        self.client.post(
            "/login",
            data={"username": "admin2", "password": "password"},
            follow_redirects=True,
        )

        response = self.client.post(
            "/admin/create-test",
            data={
                "title": "Shipping Policy Test",
                "status": "recruiting",
                "total_lab_cost": "100",
                "shipping_cost": "20",
                "donor_shipping_cost": "15",
                "donor_shipping_reimbursement": "participant",
                "donor_shipping_reimbursed_by_id": str(participant_id),
                "refund_per_donor": "0",
                "lab_name": "North Lab",
                "lab_item_name": ["MASS"],
                "lab_item_price": ["100"],
                "lab_item_vials": ["1"],
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            test = GroupTest.query.filter_by(title="Shipping Policy Test").first()
            self.assertIsNotNone(test)
            self.assertEqual(test.donor_shipping_reimbursement, "participant")
            self.assertEqual(test.donor_shipping_reimbursed_by_id, participant.id)

    def test_donor_share_becomes_negative_when_refund_exceeds_base_share(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="refund-admin", email="refund-admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            db.session.add(admin)
            db.session.flush()

            for idx in range(11):
                user = User(username=f"user{idx}", email=f"user{idx}@example.com", is_admin=False, is_active=True)
                user.set_password("password")
                db.session.add(user)
            db.session.flush()

            test = GroupTest(
                title="Refund Test",
                status="recruiting",
                total_lab_cost=184.83,
                shipping_cost=0.0,
                refund_per_donor=20.0,
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            for idx in range(10):
                participation = Participation(
                    group_test_id=test.id,
                    user_id=idx + 2,
                    approved=True,
                    vial_donor=False,
                )
                db.session.add(participation)

            donor_participation = Participation(
                group_test_id=test.id,
                user_id=1,
                approved=True,
                vial_donor=True,
            )
            db.session.add(donor_participation)
            db.session.commit()

            costs = test.calculate_costs()

            self.assertEqual(costs["total_participants"], 11)
            self.assertEqual(costs["total_donors"], 1)
            self.assertEqual(costs["total_non_donors"], 10)
            self.assertEqual(costs["donor_pays"], -3.2)
            self.assertEqual(costs["non_donor_pays"], 18.8)

    def test_donor_shipping_cost_is_added_to_shared_pool_and_credited(self):
        with self.app.app_context():
            db.create_all()
            admin = User(username="shipping-admin", email="shipping-admin@example.com", is_admin=True, is_active=True)
            admin.set_password("password")
            db.session.add(admin)
            db.session.flush()

            donor = User(username="donor", email="donor@example.com", is_admin=False, is_active=True)
            donor.set_password("password")
            non_donor = User(username="non-donor", email="non-donor@example.com", is_admin=False, is_active=True)
            non_donor.set_password("password")
            db.session.add_all([donor, non_donor])
            db.session.flush()

            test = GroupTest(
                title="Shipping Test",
                status="recruiting",
                total_lab_cost=100.0,
                shipping_cost=20.0,
                donor_shipping_cost=15.0,
                donor_shipping_reimbursement='credit',
                refund_per_donor=0.0,
                created_by=admin.id,
            )
            db.session.add(test)
            db.session.flush()

            db.session.add_all([
                Participation(group_test_id=test.id, user_id=donor.id, approved=True, vial_donor=True),
                Participation(group_test_id=test.id, user_id=non_donor.id, approved=True, vial_donor=False),
            ])
            db.session.commit()

            costs = test.calculate_costs()

            self.assertEqual(costs["total_fixed_cost"], 135.0)
            self.assertEqual(costs["base_per_person"], 67.5)
            self.assertEqual(costs["donor_pays"], 52.5)
            self.assertEqual(costs["non_donor_pays"], 67.5)


if __name__ == "__main__":
    unittest.main()
