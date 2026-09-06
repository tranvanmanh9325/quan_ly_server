"""
Unit tests for MediaProcessor archive extraction, password detection, and decryption engine.
"""

import base64
import io
import sys
import unittest
import zipfile
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.media_processor import (
    ArchiveInvalidPasswordError,
    ArchivePasswordRequiredError,
    MediaProcessor,
    extract_password_from_text,
)

# Minimal encrypted ZIP (ZipCrypto, password="123456", contains "secret.txt")
ENCRYPTED_ZIP_BYTES = base64.b64decode(
    "UEsDBBQAAQAAAAAAIVwAFNVlNwAAACsAAAAKAAAAc2VjcmV0LnR4dIB+r0WaIqyk40puTZEvcsduVgCB1c2TzpJ+oZjv233Zza1nc8VOJMXZfVgGNZv1+DKiontu0URQSwECFAAUAAEAAAAAACFcABTVZTcAAAArAAAACgAAAAAAAAAAAAAAAAAAAAAAc2VjcmV0LnR4dFBLBQYAAAAAAQABADgAAABfAAAAAAA="
)


class TestArchiveProcessor(unittest.TestCase):
    def test_extract_password_from_text(self):
        self.assertEqual(extract_password_from_text("pass: 123456"), "123456")
        self.assertEqual(extract_password_from_text("pass:123456"), "123456")
        self.assertEqual(extract_password_from_text("mật khẩu là: SecretKey99"), "SecretKey99")
        self.assertEqual(extract_password_from_text("mật khẩu: Secret123"), "Secret123")
        self.assertEqual(extract_password_from_text("mk: my_pass"), "my_pass")
        self.assertEqual(extract_password_from_text("password = 'super secret pass'"), "super secret pass")
        self.assertEqual(extract_password_from_text('pass là "complex pass 2026"'), "complex pass 2026")
        self.assertIsNone(extract_password_from_text("Chào em, hãy kiểm tra file này giúp anh"))

    def test_unencrypted_zip_extraction(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.txt", "Nội dung văn bản thử nghiệm")
            zf.writestr("code.py", "print('hello world')")
        data = buf.getvalue()

        members = MediaProcessor._unpack_archive_members(data, "test.zip")
        self.assertEqual(len(members), 2)
        names = [m[0] for m in members]
        self.assertIn("test.txt", names)
        self.assertIn("code.py", names)

    def test_encrypted_zip_password_required(self):
        # Attempting without password must raise ArchivePasswordRequiredError
        with self.assertRaises(ArchivePasswordRequiredError):
            MediaProcessor._unpack_archive_members(ENCRYPTED_ZIP_BYTES, "protected.zip", password=None)

    def test_encrypted_zip_wrong_password(self):
        # Attempting with wrong password must raise ArchiveInvalidPasswordError
        with self.assertRaises(ArchiveInvalidPasswordError):
            MediaProcessor._unpack_archive_members(ENCRYPTED_ZIP_BYTES, "protected.zip", password="wrong_pass")

    def test_encrypted_zip_correct_password(self):
        members = MediaProcessor._unpack_archive_members(ENCRYPTED_ZIP_BYTES, "protected.zip", password="123456")
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0][0], "secret.txt")
        self.assertEqual(members[0][2].decode("utf-8"), "Dữ liệu mật đã được giải mã!")


if __name__ == "__main__":
    unittest.main()
