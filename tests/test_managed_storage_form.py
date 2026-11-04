import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, db
from app.models import NotificationConfig, User


class ManagedStorageFormTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True, "WTF_CSRF_ENABLED": False, "SESSION_PROTECTION": None,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(Path(self.temp_dir.name) / "test.db"),
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        user = User(username="admin", email="admin@example.com", password_hash="unused", is_admin=True, is_active=True)
        db.session.add(user)
        db.session.add(NotificationConfig(key="storage_bucket", value="local-bucket"))
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True
        self.values = {
            "storage_enabled": "yes", "storage_provider": "do", "storage_bucket": "managed-bucket",
            "storage_region": "nyc3", "storage_access_key_id": "managed-access-key",
            "storage_secret_access_key": "secret-never-rendered",
        }
        self.environment = patch.dict(os.environ, {
            "GTT_DEPLOYMENT_MODE": "managed", "GTT_MANAGED_INTEGRATIONS": json.dumps(self.values),
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()

    def test_form_shows_effective_managed_values_without_exposing_secret(self):
        response = self.client.get("/admin/storage-config")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="managed-bucket"', response.data)
        self.assertNotIn(b'value="local-bucket"', response.data)
        self.assertIn(b"Settings managed by the control plane", response.data)
        self.assertNotIn(b"secret-never-rendered", response.data)
        self.assertIn(b"disabled", response.data)
        self.assertIn(b"Current status: Enabled", response.data)

    def test_post_cannot_replace_managed_values_but_can_save_local_fields(self):
        response = self.client.post("/admin/storage-config", data={
            "storage_enabled": "", "storage_provider": "aws", "storage_bucket": "attacker-bucket",
            "storage_secret_access_key": "attacker-secret", "storage_path_prefix": "tenant-files",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(NotificationConfig.query.filter_by(key="storage_bucket").one().value, "local-bucket")
        self.assertIsNone(NotificationConfig.query.filter_by(key="storage_secret_access_key").first())
        self.assertEqual(NotificationConfig.query.filter_by(key="storage_path_prefix").one().value, "tenant-files")
        from app.storage import get_storage_settings
        self.assertEqual(get_storage_settings()["bucket"], "managed-bucket")

    def test_removing_override_restores_local_storage_settings(self):
        with patch.dict(os.environ, {"GTT_MANAGED_INTEGRATIONS": "{}"}):
            response = self.client.get("/admin/storage-config")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'value="local-bucket"', response.data)
            self.assertNotIn(b"Settings managed by the control plane", response.data)

    def test_configuration_summary_uses_the_same_effective_values_as_storage(self):
        from app.routes import _config_values_map
        self.assertEqual(_config_values_map()["storage_bucket"], "managed-bucket")

    def test_standalone_still_uses_and_edits_database_settings(self):
        with patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "standalone"}):
            response = self.client.get("/admin/storage-config")
            self.assertIn(b'value="local-bucket"', response.data)
            self.assertNotIn(b"Settings managed by the control plane", response.data)
            response = self.client.post("/admin/storage-config", data={
                "storage_provider": "aws", "storage_bucket": "new-local-bucket",
            })
            self.assertEqual(response.status_code, 302)
            self.assertEqual(NotificationConfig.query.filter_by(key="storage_bucket").one().value, "new-local-bucket")
