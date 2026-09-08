"""
Unit tests for Smart Archive Password Recovery Engine.
"""

import shutil
import unittest
from app.services.archive_recovery import (
    generate_candidate_passwords,
    run_archive_recovery_local,
)


class TestArchiveRecovery(unittest.TestCase):
    def test_generate_candidates_with_name_and_year(self):
        clues = ["Kirito", "2005"]
        candidates = generate_candidate_passwords(clues)
        self.assertGreater(len(candidates), 50)
        # Expected variations must be generated
        self.assertIn("Kirito", candidates)
        self.assertIn("kirito", candidates)
        self.assertIn("Kirito2005", candidates)
        self.assertIn("kirito2005", candidates)
        self.assertIn("Kirito@2005", candidates)

    def test_custom_passwords_priority(self):
        custom = ["MySecret123!", "PersonalSpecialPass"]
        candidates = generate_candidate_passwords(clues=["test"], custom_candidates=custom)
        # Custom candidates must appear at the top
        self.assertEqual(candidates[0], "MySecret123!")
        self.assertEqual(candidates[1], "PersonalSpecialPass")

    def test_leetspeak_mutation(self):
        clues = ["manh"]
        candidates = generate_candidate_passwords(clues)
        # 'a' transformed to '@' in leetspeak
        self.assertTrue(any("m@nh" in c for c in candidates))

    def test_empty_clues_fallback(self):
        candidates = generate_candidate_passwords([])
        # Should at least contain common default passwords and PINs
        self.assertGreater(len(candidates), 10)
        self.assertIn("123456", candidates)
        self.assertIn("1234", candidates)

    def test_pin_sweep_included(self):
        candidates = generate_candidate_passwords([], include_pin_sweep=True, max_candidates=1500)
        # Should contain common 4-digit PIN patterns
        self.assertIn("0000", candidates)
        self.assertIn("0123", candidates)

    @unittest.skipUnless(shutil.which("7z"), "7z binary required on PATH")
    def test_run_archive_recovery_local_with_mock(self):
        # Only runs when 7z is installed (e.g. inside Docker or Linux host)
        res = run_archive_recovery_local(
            archive_path_or_bytes=b"dummy_data",
            candidates=["123456", "admin"],
            filename="dummy.zip",
        )
        self.assertIsInstance(res, dict)
        self.assertIn("found", res)


if __name__ == "__main__":
    unittest.main()
