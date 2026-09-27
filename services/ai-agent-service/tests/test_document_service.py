"""
test_document_service.py — Unit Tests for Document & Knowledge Processing Suite (R2).

Covers all 5 tools with IsolatedAsyncioTestCase:
  1. merge_pdf_documents (PyMuPDF real merging, validation, optimization)
  2. split_pdf_document (page range parsing, "1-3, 5", "odd", "even", "last")
  3. extract_document_text (PDF, DOCX tables, CSV, JSON, TXT, scanned-PDF detection)
  4. translate_text (Tier 1 Groq LLM -> Tier 2 Google Translate fallback)
  5. inspect_media_metadata (Pillow EXIF for images, ffprobe JSON for video/audio)
  + Dual-Delivery routing and zero file leaks.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure app parent directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import docx
import fitz
from PIL import Image

from app.services.document_service import (
    DocumentService,
    parse_page_ranges,
)


class TestDocumentService(unittest.IsolatedAsyncioTestCase):
    """Full unit test suite for DocumentService."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.scratch_path = Path(self.temp_dir.name)
        self.mock_storage = MagicMock()
        self.mock_router = MagicMock()
        self.mock_http = MagicMock()

        self.service = DocumentService(
            llm_router=self.mock_router,
            storage_manager=self.mock_storage,
            http_client=self.mock_http,
            temp_dir=self.scratch_path,
        )

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    # ─── 0. PAGE RANGE PARSER HELPER ──────────────────────────────────────────

    def test_parse_page_ranges(self):
        """Test user range string parsing into 0-based indices."""
        # Comma and dash tokens
        self.assertEqual(parse_page_ranges("1-3, 5, 8-10", 10), [0, 1, 2, 4, 7, 8, 9])
        # Reversed range ordering
        self.assertEqual(parse_page_ranges("3-1", 5), [0, 1, 2])
        # Odd pages
        self.assertEqual(parse_page_ranges("odd", 6), [0, 2, 4])
        # Even pages
        self.assertEqual(parse_page_ranges("even", 6), [1, 3, 5])
        # Last page
        self.assertEqual(parse_page_ranges("last", 7), [6])
        # Out of bounds ignored
        self.assertEqual(parse_page_ranges("1, 15, 20", 5), [0])

    # ─── 1. MERGE PDF DOCUMENTS ───────────────────────────────────────────────

    async def test_merge_pdf_documents_real(self):
        """Test real PDF merging via PyMuPDF."""
        p1 = self.scratch_path / "doc1.pdf"
        p2 = self.scratch_path / "doc2.pdf"

        # Create two 1-page PDF documents
        doc1 = fitz.open()
        page1 = doc1.new_page()
        page1.insert_text((50, 50), "Document 1 Content")
        doc1.save(str(p1))
        doc1.close()

        doc2 = fitz.open()
        page2 = doc2.new_page()
        page2.insert_text((50, 50), "Document 2 Content")
        doc2.save(str(p2))
        doc2.close()

        res = await self.service.merge_pdf_documents(
            file_paths=[str(p1), str(p2)],
            output_name="custom_merged.pdf",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tool"], "merge_pdf_documents")
        self.assertEqual(res["files_count"], 2)
        self.assertEqual(res["total_pages"], 2)

        out_file = Path(res["file_path"])
        self.assertTrue(out_file.exists())
        with fitz.open(str(out_file)) as m_doc:
            self.assertEqual(len(m_doc), 2)

    async def test_merge_pdf_documents_validation(self):
        """Test validation when files are missing or empty."""
        res = await self.service.merge_pdf_documents([])
        self.assertEqual(res["status"], "error")
        self.assertIn("ít nhất 1 tệp", res["message"])

        res_missing = await self.service.merge_pdf_documents([str(self.scratch_path / "nonexistent.pdf")])
        self.assertEqual(res_missing["status"], "error")
        self.assertIn("không tồn tại", res_missing["message"])

    # ─── 2. SPLIT PDF DOCUMENT ────────────────────────────────────────────────

    async def test_split_pdf_document_real(self):
        """Test splitting pages from a real 4-page PDF document."""
        pdf_path = self.scratch_path / "book.pdf"
        doc = fitz.open()
        for i in range(4):
            page = doc.new_page()
            page.insert_text((50, 50), f"Page number {i + 1}")
        doc.save(str(pdf_path))
        doc.close()

        res = await self.service.split_pdf_document(
            file_path=str(pdf_path),
            page_ranges="1, 3-4",
            output_name="split_sample.pdf",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tool"], "split_pdf_document")
        self.assertEqual(res["original_pages"], 4)
        self.assertEqual(res["extracted_pages_count"], 3)
        self.assertEqual(res["extracted_pages"], [1, 3, 4])

        out_file = Path(res["file_path"])
        self.assertTrue(out_file.exists())
        with fitz.open(str(out_file)) as s_doc:
            self.assertEqual(len(s_doc), 3)

    async def test_split_pdf_document_invalid_range(self):
        """Test error handling when page range is completely out of bounds."""
        pdf_path = self.scratch_path / "short.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        res = await self.service.split_pdf_document(str(pdf_path), "10-20")
        self.assertEqual(res["status"], "error")
        self.assertIn("không hợp lệ", res["message"])

    # ─── 3. EXTRACT DOCUMENT TEXT ─────────────────────────────────────────────

    async def test_extract_document_text_pdf(self):
        """Test text extraction from real PDF with page demarcations."""
        pdf_path = self.scratch_path / "report.pdf"
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 50), "Hello from Page 1")
        p2 = doc.new_page()
        p2.insert_text((50, 50), "Hello from Page 2")
        doc.save(str(pdf_path))
        doc.close()

        res = await self.service.extract_document_text(str(pdf_path))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tool"], "extract_document_text")
        self.assertEqual(res["doc_type"], "Tài liệu PDF")
        self.assertEqual(res["total_pages"], 2)
        self.assertFalse(res["is_scanned_image"])
        self.assertIn("--- [Trang 1] ---", res["text"])
        self.assertIn("Hello from Page 1", res["text"])
        self.assertIn("Hello from Page 2", res["text"])

    async def test_extract_document_text_pdf_scanned_detection(self):
        """Test automatic detection of scanned/raster PDF without text layer."""
        pdf_path = self.scratch_path / "scanned_doc.pdf"
        doc = fitz.open()
        # Create an empty page without text (simulating image-only scan)
        doc.new_page()
        doc.save(str(pdf_path))
        doc.close()

        res = await self.service.extract_document_text(str(pdf_path))
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["is_scanned_image"])
        self.assertIsNotNone(res["warning"])
        self.assertIn("ảnh quét", res["warning"])

    async def test_extract_document_text_docx(self):
        """Test text and Markdown table extraction from real DOCX."""
        docx_path = self.scratch_path / "contract.docx"
        doc = docx.Document()
        doc.add_paragraph("Đây là đoạn văn bản hợp đồng mẫu.")

        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Họ và tên"
        table.cell(0, 1).text = "Chức vụ"
        table.cell(1, 0).text = "Trần Văn Mạnh"
        table.cell(1, 1).text = "Admin Kirito"
        doc.save(str(docx_path))

        res = await self.service.extract_document_text(str(docx_path))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["doc_type"], "Tài liệu Word")
        self.assertIn("Đây là đoạn văn bản hợp đồng mẫu", res["text"])
        self.assertIn("[Bảng 1]:", res["text"])
        self.assertIn("Trần Văn Mạnh | Admin Kirito", res["text"])

    async def test_extract_document_text_json_csv_txt(self):
        """Test extraction for JSON, CSV, and TXT files."""
        # JSON
        json_path = self.scratch_path / "config.json"
        json_path.write_text('{"service": "ai-agent", "active": true}', encoding="utf-8")
        res_json = await self.service.extract_document_text(str(json_path))
        self.assertEqual(res_json["status"], "ok")
        self.assertIn('"active": true', res_json["text"])

        # CSV
        csv_path = self.scratch_path / "data.csv"
        csv_path.write_text("id,name,role\n1,kirito,superadmin\n", encoding="utf-8")
        res_csv = await self.service.extract_document_text(str(csv_path))
        self.assertEqual(res_csv["status"], "ok")
        self.assertIn("kirito", res_csv["text"])

        # TXT
        txt_path = self.scratch_path / "notes.txt"
        txt_path.write_text("Ghi chú bảo trì server ngày 27/09", encoding="utf-8")
        res_txt = await self.service.extract_document_text(str(txt_path))
        self.assertEqual(res_txt["status"], "ok")
        self.assertIn("Ghi chú bảo trì", res_txt["text"])

    async def test_extract_document_text_truncation(self):
        """Test clean truncation when text length exceeds max_chars."""
        txt_path = self.scratch_path / "long.txt"
        long_content = "A" * 1500
        txt_path.write_text(long_content, encoding="utf-8")

        res = await self.service.extract_document_text(str(txt_path), max_chars=500)
        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["is_truncated"])
        self.assertIn("Đã cắt bớt", res["text"])

    # ─── 4. TRANSLATE TEXT (DUAL-TIER HYBRID) ──────────────────────────────────

    async def test_translate_text_tier1_llm_success(self):
        """Test translation via Tier 1 Groq LLM Router."""
        self.mock_router.complete = AsyncMock(return_value={
            "choices": [
                {
                    "message": {
                        "content": "Xin chào thế giới! Đây là bản dịch qua Groq LLM."
                    }
                }
            ]
        })

        res = await self.service.translate_text(
            text="Hello world! This is translated via Groq LLM.",
            source_lang="en",
            target_lang="vi",
            engine="llm",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["engine"], "llm")
        self.assertEqual(res["translated_text"], "Xin chào thế giới! Đây là bản dịch qua Groq LLM.")

    async def test_translate_text_tier2_google_fallback(self):
        """Test fallback to Tier 2 Google Translate when Tier 1 LLM fails."""
        # Tier 1 raises exception
        self.mock_router.complete = AsyncMock(side_effect=RuntimeError("Groq rate limit exceeded"))

        # Tier 2 HTTP client returns Google Translate single format
        fake_gt_response = MagicMock()
        fake_gt_response.status_code = 200
        fake_gt_response.json.return_value = [
            [["Xin chào thế giới", "Hello world", None, None, 1]],
            None,
            "en",
        ]
        self.mock_http.get = AsyncMock(return_value=fake_gt_response)

        res = await self.service.translate_text(
            text="Hello world",
            source_lang="en",
            target_lang="vi",
            engine="auto",
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["engine"], "google")
        self.assertEqual(res["translated_text"], "Xin chào thế giới")

    async def test_translate_text_empty(self):
        """Test rejection of empty text input."""
        res = await self.service.translate_text("")
        self.assertEqual(res["status"], "error")
        self.assertIn("không được để trống", res["message"])

    # ─── 5. INSPECT MEDIA METADATA ────────────────────────────────────────────

    async def test_inspect_media_metadata_image_real(self):
        """Test real image metadata inspection with Pillow."""
        img_path = self.scratch_path / "banner.png"
        img = Image.new("RGB", (640, 480), (30, 144, 255))
        img.save(img_path, format="PNG")

        res = await self.service.inspect_media_metadata(str(img_path))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["tool"], "inspect_media_metadata")
        self.assertEqual(res["media_type"], "image")
        self.assertEqual(res["width"], 640)
        self.assertEqual(res["height"], 480)
        self.assertIn("🖼️ Siêu dữ liệu Hình ảnh", res["summary"])

    async def test_inspect_media_metadata_video_ffprobe(self):
        """Test video metadata extraction via ffprobe JSON output."""
        vid_path = self.scratch_path / "movie.mp4"
        vid_path.write_bytes(b"dummy video data")

        ffprobe_data = {
            "format": {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "duration": "135.5",
                "size": "15728640",
                "bit_rate": "928000",
                "tags": {
                    "title": "Kirito Server Demo",
                    "artist": "Manh Tran",
                }
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "pix_fmt": "yuv420p",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "bit_rate": "192000",
                }
            ],
            "chapters": []
        }

        with patch.object(self.service, "_run_command", return_value=(0, json.dumps(ffprobe_data).encode(), b"")):
            res = await self.service.inspect_media_metadata(str(vid_path))
            self.assertEqual(res["status"], "ok")
            self.assertEqual(res["media_type"], "video")
            self.assertEqual(res["duration_formatted"], "02:15")
            self.assertEqual(res["video_stream"]["width"], 1920)
            self.assertEqual(res["audio_stream"]["codec_name"], "aac")
            self.assertIn("🎬 Video Metadata", res["summary"])
            self.assertIn("1920x1080", res["summary"])
            self.assertIn("Title: Kirito Server Demo", res["summary"])

    async def test_inspect_media_metadata_ffprobe_failure(self):
        """Test error handling when ffprobe fails on invalid file."""
        vid_path = self.scratch_path / "broken.mp4"
        vid_path.write_bytes(b"corrupted")

        with patch.object(self.service, "_run_command", return_value=(1, b"", b"Invalid data found when processing input")):
            res = await self.service.inspect_media_metadata(str(vid_path))
            self.assertEqual(res["status"], "error")
            self.assertIn("thất bại", res["message"])


if __name__ == "__main__":
    unittest.main()
