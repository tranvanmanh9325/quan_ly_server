"""
Unit tests for MediaProcessor archive extraction, password detection, and decryption engine.
"""

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
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.setpassword(b"123456")
            zf.writestr("secret.txt", "Tài liệu mật cần bảo vệ", compress_type=zipfile.ZIP_DEFLATED)
        data = buf.getvalue()

        # Attempting without password must raise ArchivePasswordRequiredError
        with self.assertRaises(ArchivePasswordRequiredError):
            MediaProcessor._unpack_archive_members(data, "protected.zip", password=None)

    def test_encrypted_zip_wrong_password(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.setpassword(b"correct_pass")
            zf.writestr("secret.txt", "Tài liệu mật", compress_type=zipfile.ZIP_DEFLATED)
        data = buf.getvalue()

        # Attempting with wrong password must raise ArchiveInvalidPasswordError
        with self.assertRaises(ArchiveInvalidPasswordError):
            MediaProcessor._unpack_archive_members(data, "protected.zip", password="wrong_pass")

    def test_encrypted_zip_correct_password(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.setpassword(b"my_secure_pass")
            zf.writestr("secret.txt", "Dữ liệu mật đã được giải mã!", compress_type=zipfile.ZIP_DEFLATED)
        data = buf.getvalue()

        members = MediaProcessor._unpack_archive_members(data, "protected.zip", password="my_secure_pass")
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0][0], "secret.txt")
        self.assertEqual(members[0][2].decode("utf-8"), "Dữ liệu mật đã được giải mã!")


if __name__ == "__main__":
    unittest.main()
