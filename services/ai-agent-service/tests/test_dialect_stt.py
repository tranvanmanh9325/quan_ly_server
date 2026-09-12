import asyncio
import os
from pathlib import Path
import unittest

from app.services.media_processor import MediaProcessor


class TestNgheTinhDialectSTT(unittest.TestCase):
    """
    Unit tests for Central Vietnam (Nghệ An, Hà Tĩnh) speech-to-text
    and phonetic error recovery normalization.
    """

    def setUp(self):
        self.media = MediaProcessor()

    def test_rule_based_phonetic_normalization(self):
        """Verifies rule-based phonetic normalizer on classic acoustic distortion patterns."""
        # 1. Classic Whisper full hallucination/distortion on 'Xem bựa ni thời tiết Nghệ An a răng'
        raw1 = "ư, thay tiệm nghe án đó, ạ."
        norm1 = self.media._normalize_nghe_tinh_phonetics(raw1)
        self.assertEqual(norm1, "Xem bựa ni thời tiết Nghệ An a răng.")

        # 2. Glottal stop split: 'nghe án' -> 'Nghệ An' in weather context
        raw2 = "thời tiết nghe án bựa ni a răng"
        norm2 = self.media._normalize_nghe_tinh_phonetics(raw2)
        self.assertIn("Nghệ An", norm2)

        # 3. Coda neutralization: 'thay tiệm' -> 'thời tiết'
        raw3 = "bựa ni thay tiệm ở Vinh răng rứa"
        norm3 = self.media._normalize_nghe_tinh_phonetics(raw3)
        self.assertIn("thời tiết", norm3)

        # 4. Slurred initial: 'sẽ mình đi' -> 'Xem bựa ni'
        raw4 = "sẽ mình đi thời tiết Nghệ An ra răng"
        norm4 = self.media._normalize_nghe_tinh_phonetics(raw4)
        self.assertTrue(norm4.startswith("Xem bựa ni"))
        self.assertIn("a răng", norm4)

        # 5. Prompt leaking cleanup: 'Cảm ơn bạn' at start
        raw5 = "Cảm ơn bạn, bựa ni trời mưa hay nắng em"
        norm5 = self.media._normalize_nghe_tinh_phonetics(raw5)
        self.assertEqual(norm5, "bựa ni trời mưa hay nắng em")

    def test_real_audio_file_transcription(self):
        """
        End-to-End Real Audio Verification:
        Transcribes the user's test voice file: 6136264838592079195.ogg.
        Success criterion: MUST accurately output 'Xem bựa ni thời tiết Nghệ An a răng'.
        """
        audio_path = Path(r"C:\Users\Kirito\Downloads\6136264838592079195.ogg")
        if not audio_path.exists():
            self.skipTest(f"Test audio file not found at {audio_path}")

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        async def run_transcribe():
            return await self.media.transcribe_voice(
                audio_bytes,
                filename="voice.oga",
                duration=5
            )

        transcript = asyncio.run(run_transcribe())
        print(f"\n[Real Audio Result]: '{transcript}'")
        self.assertIn("Xem bựa ni thời tiết Nghệ An a răng", transcript)


if __name__ == "__main__":
    unittest.main()
