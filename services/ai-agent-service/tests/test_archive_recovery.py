"""
Unit tests for Smart Archive Password Recovery Engine.
"""

import unittest
from app.services.archive_recovery import generate_candidate_passwords


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
        # Should at least contain common default passwords
        self.assertGreater(len(candidates), 10)
        self.assertIn("123456", candidates)


if __name__ == "__main__":
    unittest.main()
