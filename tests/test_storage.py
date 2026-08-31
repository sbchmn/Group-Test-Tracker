import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import NotificationConfig
from app.storage import StorageUploadError, upload_result_image


class _FakeS3Client:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


class StorageUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.db_path}",
        })

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _seed_storage_config(self, allowed_formats="JPEG,PNG,WEBP,GIF,PDF"):
        db.session.add_all([
            NotificationConfig(key="storage_enabled", value="true"),
            NotificationConfig(key="storage_provider", value="aws"),
            NotificationConfig(key="storage_bucket", value="result-bucket"),
            NotificationConfig(key="storage_region", value="us-east-1"),
            NotificationConfig(key="storage_access_key_id", value="abc"),
            NotificationConfig(key="storage_secret_access_key", value="xyz"),
            NotificationConfig(key="storage_allowed_formats", value=allowed_formats),
        ])
        db.session.commit()

    def test_upload_result_image_accepts_pdf_and_sets_pdf_content_type(self):
        with self.app.app_context():
            db.create_all()
            self._seed_storage_config()

            fake_client = _FakeS3Client()
            file_storage = FileStorage(
                stream=io.BytesIO(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"),
                filename="coa.pdf",
                content_type="application/pdf",
            )

            with patch("app.storage._build_client", return_value=fake_client):
                object_key = upload_result_image(file_storage, "group-tests")

            self.assertTrue(object_key.endswith(".pdf"))
            self.assertEqual(len(fake_client.calls), 1)
            call = fake_client.calls[0]
            self.assertEqual(call["ContentType"], "application/pdf")
            self.assertEqual(call["Bucket"], "result-bucket")

    def test_upload_result_image_rejects_invalid_pdf_payload(self):
        with self.app.app_context():
            db.create_all()
            self._seed_storage_config()

            file_storage = FileStorage(
                stream=io.BytesIO(b"not-a-real-pdf"),
                filename="coa.pdf",
                content_type="application/pdf",
            )

            with patch("app.storage._build_client", return_value=_FakeS3Client()):
                with self.assertRaises(StorageUploadError):
                    upload_result_image(file_storage, "public-results")


if __name__ == "__main__":
    unittest.main()
