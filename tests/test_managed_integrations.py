import json
import os
import unittest
from unittest.mock import patch

from app.managed_integrations import managed_integration_value


class ManagedIntegrationTests(unittest.TestCase):
    def test_managed_values_override_existing_configuration_keys(self):
        with patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "managed", "GTT_MANAGED_INTEGRATIONS": json.dumps({"storage_bucket": "tenant-bucket", "mailjet_secret_key": "tenant-secret"})}):
            self.assertEqual(managed_integration_value("storage_bucket"), (True, "tenant-bucket"))
            self.assertEqual(managed_integration_value("mailjet_secret_key"), (True, "tenant-secret"))
            self.assertEqual(managed_integration_value("storage_region"), (False, None))
            from app.storage import get_storage_settings
            from app.notifications import _get_config
            with patch("app.storage.NotificationConfig") as storage_config, patch("app.notifications.NotificationConfig") as mail_config:
                storage_config.query.filter_by.return_value.first.return_value = None
                self.assertEqual(get_storage_settings()["bucket"], "tenant-bucket")
                self.assertEqual(_get_config("mailjet_secret_key"), "tenant-secret")
                mail_config.query.filter_by.assert_not_called()

    def test_standalone_ignores_managed_settings(self):
        with patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "standalone", "GTT_MANAGED_INTEGRATIONS": '{"storage_bucket":"ignored"}'}):
            self.assertEqual(managed_integration_value("storage_bucket"), (False, None))

    def test_invalid_configuration_never_exposes_secret_values(self):
        for value in ('invalid secret text', '{"storage_bucket": 42}', '{"DATABASE_URL":"secret"}'):
            with self.subTest(value=value), patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "managed", "GTT_MANAGED_INTEGRATIONS": value}):
                with self.assertRaisesRegex(RuntimeError, "^Managed integration configuration is invalid$"):
                    managed_integration_value("storage_bucket")

    def test_email_channel_recognizes_managed_credentials(self):
        from app.bot_channels import is_configured
        values = {"mailjet_api_key": "api", "mailjet_secret_key": "secret", "mailjet_sender_email": "sender@example.com"}
        with patch.dict(os.environ, {"GTT_DEPLOYMENT_MODE": "managed", "GTT_MANAGED_INTEGRATIONS": json.dumps(values)}):
            self.assertTrue(is_configured("email", {}))
