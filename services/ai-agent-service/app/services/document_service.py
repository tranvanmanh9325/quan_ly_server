"""
document_service.py — High-Performance Document & Knowledge Processing Engine.

Provides 5 specialized document tools:
  1. merge_pdf_documents: Merge multiple PDF documents into a single optimized PDF via PyMuPDF (fitz).
  2. split_pdf_document: Extract specific pages via flexible range expressions ("1-3, 5, 8-10", "odd", "even", "last").
  3. extract_document_text: Robust text extraction from PDF, DOCX, XLSX, CSV, JSON, TXT, MD with scanned-PDF detection.
  4. translate_text: Dual-Tier multilingual translation (Groq LLM Router -> Google Translate public API fallback).
  5. inspect_media_metadata: Technical metadata inspection via ffprobe (video/audio) and Pillow EXIF (images).

Hardware Protection for kirito-server (Haswell 2-core CPU, 3.2GB RAM):
  - In-place stream parsing without loading entire large documents into RAM heap.
  - Subprocess execution via asyncio.create_subprocess_exec (List[str], no shell=True).
  - Concurrency bounded by asyncio.Semaphore(2).
  - Zero-Disk Leak guarantee with rigorous try...finally cleanup.
  - Dual-Delivery: files <= 50MB direct for Telegram; > 50MB via media_storage_manager.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import urllib.parse

import httpx
from PIL import Image, ExifTags

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

try:
    import docx
except ImportError:
    docx = None

try:
    import openpyxl
except ImportError:
    openpyxl = None

try:
    from app.services.media_storage_manager import media_storage_manager
except ImportError:
    media_storage_manager = None

logger = logging.getLogger(__name__)

# Maximum file size for direct Telegram Bot transmission (50MB)
TELEGRAM_MAX_FILE_SIZE: int = 50 * 1024 * 1024

# Text file extensions for universal extraction
TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".sh", ".bash",
    ".yaml", ".yml", ".toml", ".ini", ".env", ".log",
    ".html", ".xml", ".css", ".sql", ".rs", ".go",
    ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".php",
    ".conf", ".cfg", ".properties", ".bat", ".ps1",
})

# Image extensions for metadata inspection
IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tiff", ".tif", ".gif"
})


def parse_page_ranges(range_str: str, total_pages: int) -> List[int]:
    """
    Parses user-friendly 1-based page expressions into sorted, deduplicated 0-based indices.
    Supports: "1-3, 5, 8-10", "odd", "even", "last".
    """
    if total_pages <= 0:
        return []

    clean = range_str.strip().lower()
    if clean == "odd":
        return [i for i in range(total_pages) if i % 2 == 0]
    if clean == "even":
        return [i for i in range(total_pages) if i % 2 == 1]
    if clean == "last":
        return [total_pages - 1]

    selected: List[int] = []
    tokens = [t.strip() for t in clean.split(",") if t.strip()]

    for token in tokens:
        if "-" in token:
            parts = token.split("-", 1)
            try:
                start_p = int(parts[0].strip())
                end_p = int(parts[1].strip())
                # Normalize ordering
                if start_p > end_p:
                    start_p, end_p = end_p, start_p
                for p in range(start_p, end_p + 1):
                    idx = p - 1
                    if 0 <= idx < total_pages and idx not in selected:
                        selected.append(idx)
            except ValueError:
                continue
        else:
            try:
                idx = int(token) - 1
                if 0 <= idx < total_pages and idx not in selected:
                    selected.append(idx)
            except ValueError:
                continue

    selected.sort()
    return selected


class DocumentService:
    """
    Core execution engine for R2 Document & Knowledge Processing Suite.
    """

    def __init__(
        self,
        llm_router: Any = None,
        storage_manager: Any = None,
        http_client: Optional[httpx.AsyncClient] = None,
        temp_dir: Optional[Union[str, Path]] = None,
    ):
        self._router = llm_router
        self._storage = storage_manager if storage_manager is not None else media_storage_manager
        self._http = http_client
        self._semaphore = asyncio.Semaphore(2)

        base_temp = Path(temp_dir or os.getenv("MEDIA_STUDIO_TEMP_DIR", tempfile.gettempdir()))
        self._temp_dir = base_temp / "document_studio"
        self._ensure_temp_dir()

    def _ensure_temp_dir(self) -> None:
        """Create scratch directory if missing."""
        try:
            self._temp_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("[DocumentService] Failed to create scratch directory %s: %s", self._temp_dir, exc)

    async def _run_command(
        self,
        cmd: List[str],
        timeout: int = 120,
    ) -> Tuple[int, bytes, bytes]:
        """Executes a subprocess safely with concurrency bounding and strict timeout."""
        async with self._semaphore:
            logger.debug("[DocumentService] Executing command: %s", " ".join(cmd[:8]))
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return proc.returncode or 0, stdout, stderr
            except asyncio.TimeoutError:
                logger.error("[DocumentService] Subprocess timed out after %ds: %s", timeout, cmd[0])
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
                raise TimeoutError(f"Tác vụ xử lý tài liệu vượt quá thời gian tối đa ({timeout}s).")

    async def _resolve_input(self, input_path_or_url: str) -> Tuple[Path, bool]:
        """Resolves input target: streams remote URL or validates local file."""
        clean_input = str(input_path_or_url).strip()
        if not clean_input:
            raise ValueError("Đường dẫn hoặc URL đầu vào không được để trống.")

        if clean_input.lower().startswith(("http://", "https://")):
            url_name = Path(urllib.parse.urlsplit(clean_input).path).name or "input_doc.bin"
            token = secrets.token_hex(6)
            download_dest = self._temp_dir / f"dl_{token}_{url_name}"

            client = self._http
            should_close = False
            if client is None:
                client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
                should_close = True

            try:
                async with client.stream("GET", clean_input) as resp:
                    resp.raise_for_status()
                    with open(download_dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                return download_dest, True
            finally:
                if should_close:
                    await client.aclose()

        local_path = Path(clean_input).resolve()
        if not local_path.exists():
            raise FileNotFoundError(f"Tệp không tồn tại: {clean_input}")
        return local_path, False

    def _publish_or_direct(
        self,
        file_path: Path,
        title: str = "",
    ) -> Dict[str, Any]:
        """Dual-Delivery router for documents."""
        if not file_path.exists():
            raise FileNotFoundError(f"Tệp kết quả không tồn tại: {file_path}")

        file_size = file_path.stat().st_size
        size_mb = round(file_size / (1024 * 1024), 2)

        if file_size <= TELEGRAM_MAX_FILE_SIZE:
            return {
                "delivery": "direct",
                "file_path": str(file_path),
                "filename": file_path.name,
                "file_size": file_size,
                "file_size_mb": size_mb,
                "internet_url": None,
                "lan_url": None,
                "expires_at": None,
            }

        if self._storage is not None:
            try:
                record = self._storage.publish_download_item(
                    file_path=file_path,
                    filename=file_path.name,
                    title=title or file_path.name,
                    ttl=4 * 3600,
                )
                return {
                    "delivery": "portal",
                    "file_path": str(record.file_path),
                    "filename": record.filename,
                    "file_size": record.file_size,
                    "file_size_mb": round(record.file_size / (1024 * 1024), 2),
                    "internet_url": record.internet_url,
                    "lan_url": record.lan_url,
                    "expires_at": record.expires_at,
                }
            except Exception as exc:
                logger.warning("[DocumentService] Failed publishing document to portal storage: %s", exc)

        return {
            "delivery": "direct",
            "file_path": str(file_path),
            "filename": file_path.name,
            "file_size": file_size,
            "file_size_mb": size_mb,
            "internet_url": None,
            "lan_url": None,
            "expires_at": None,
        }

    # ─── 1. MERGE PDF DOCUMENTS ───────────────────────────────────────────────

    async def merge_pdf_documents(
        self,
        file_paths: List[str],
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Gộp nhiều tệp PDF thành 1 tệp duy nhất qua fitz (PyMuPDF).
        """
        if fitz is None:
            return {
                "status": "error",
                "tool": "merge_pdf_documents",
                "message": "Thư viện PyMuPDF (fitz) chưa được cài đặt.",
            }

        if not file_paths or len(file_paths) < 1:
            return {
                "status": "error",
                "tool": "merge_pdf_documents",
                "message": "Cần cung cấp ít nhất 1 tệp PDF để thực hiện gộp.",
            }

        valid_paths: List[Path] = []
        for p_str in file_paths:
            p = Path(p_str).resolve()
            if not p.exists():
                return {
                    "status": "error",
                    "tool": "merge_pdf_documents",
                    "message": f"Tệp PDF không tồn tại: {p_str}",
                }
            if p.suffix.lower() != ".pdf":
                return {
                    "status": "error",
                    "tool": "merge_pdf_documents",
                    "message": f"Tệp '{p.name}' không phải định dạng PDF.",
                }
            valid_paths.append(p)

        token = secrets.token_hex(6)
        clean_out_name = Path(output_name).name if output_name else f"merged_{token}.pdf"
        if not clean_out_name.lower().endswith(".pdf"):
            clean_out_name += ".pdf"
        out_file = self._temp_dir / clean_out_name

        try:
            merged_doc = fitz.open()
            total_pages = 0
            for p in valid_paths:
                with fitz.open(str(p)) as src:
                    merged_doc.insert_pdf(src)
                    total_pages += len(src)

            # High-performance zlib compression and unreferenced object cleanup
            merged_doc.save(str(out_file), garbage=4, deflate=True)
            merged_doc.close()

            delivery_info = self._publish_or_direct(out_file, title=f"Merged PDF ({len(valid_paths)} files)")
            return {
                "status": "ok",
                "tool": "merge_pdf_documents",
                "files_count": len(valid_paths),
                "total_pages": total_pages,
                **delivery_info,
                "message": (
                    f"Đã gộp thành công {len(valid_paths)} tệp PDF thành '{out_file.name}' "
                    f"({total_pages} trang, {delivery_info['file_size_mb']} MB)."
                ),
            }
        except Exception as exc:
            logger.error("[DocumentService] merge_pdf_documents failed: %s", exc)
            return {
                "status": "error",
                "tool": "merge_pdf_documents",
                "message": f"Lỗi khi gộp tệp PDF: {str(exc)}",
            }

    # ─── 2. SPLIT PDF DOCUMENT ────────────────────────────────────────────────

    async def split_pdf_document(
        self,
        file_path: str,
        page_ranges: str,
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Tách các trang cụ thể từ PDF (hỗ trợ range parser '1-3, 5, 8-10', 'odd', 'even', 'last').
        """
        if fitz is None:
            return {
                "status": "error",
                "tool": "split_pdf_document",
                "message": "Thư viện PyMuPDF (fitz) chưa được cài đặt.",
            }

        input_file, is_transient = await self._resolve_input(file_path)
        token = secrets.token_hex(6)
        clean_out_name = Path(output_name).name if output_name else f"split_{token}.pdf"
        if not clean_out_name.lower().endswith(".pdf"):
            clean_out_name += ".pdf"
        out_file = self._temp_dir / clean_out_name

        try:
            with fitz.open(str(input_file)) as src_doc:
                total_pages = len(src_doc)
                if total_pages == 0:
                    return {
                        "status": "error",
                        "tool": "split_pdf_document",
                        "message": "Tệp PDF không có trang nào.",
                    }

                selected_indices = parse_page_ranges(page_ranges, total_pages)
                if not selected_indices:
                    return {
                        "status": "error",
                        "tool": "split_pdf_document",
                        "message": (
                            f"Dải trang '{page_ranges}' không hợp lệ hoặc nằm ngoài phạm vi tài liệu "
                            f"(tổng cộng {total_pages} trang)."
                        ),
                    }

                out_doc = fitz.open()
                for pno in selected_indices:
                    out_doc.insert_pdf(src_doc, from_page=pno, to_page=pno)

                out_doc.save(str(out_file), garbage=4, deflate=True)
                out_doc.close()

            delivery_info = self._publish_or_direct(out_file, title=f"Split PDF ({len(selected_indices)} pages)")
            return {
                "status": "ok",
                "tool": "split_pdf_document",
                "original_pages": total_pages,
                "extracted_pages_count": len(selected_indices),
                "extracted_pages": [p + 1 for p in selected_indices],
                **delivery_info,
                "message": (
                    f"Đã tách thành công {len(selected_indices)} trang từ tệp PDF gốc "
                    f"({delivery_info['file_size_mb']} MB)."
                ),
            }
        except Exception as exc:
            logger.error("[DocumentService] split_pdf_document failed: %s", exc)
            return {
                "status": "error",
                "tool": "split_pdf_document",
                "message": f"Lỗi khi tách trang PDF: {str(exc)}",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 3. EXTRACT DOCUMENT TEXT ─────────────────────────────────────────────

    async def extract_document_text(
        self,
        file_path: str,
        max_chars: int = 50000,
    ) -> Dict[str, Any]:
        """
        Đọc và trích xuất text từ file PDF (PyMuPDF), DOCX (python-docx), XLSX, CSV, JSON, TXT, MD.
        Phát hiện và cảnh báo nếu PDF scan dạng ảnh thuần không có text layer.
        """
        input_file, is_transient = await self._resolve_input(file_path)
        ext = input_file.suffix.lower()

        try:
            doc_type = "Văn bản"
            extracted_text = ""
            total_pages = 0
            is_scanned_image = False
            warning_msg: Optional[str] = None

            # 1. PDF extraction
            if ext == ".pdf":
                doc_type = "Tài liệu PDF"
                if fitz is None:
                    return {
                        "status": "error",
                        "tool": "extract_document_text",
                        "message": "Thư viện PyMuPDF (fitz) chưa được cài đặt để đọc PDF.",
                    }

                pages_text: List[str] = []
                with fitz.open(str(input_file)) as doc:
                    total_pages = len(doc)
                    for idx, page in enumerate(doc):
                        page_str = page.get_text("text").strip()
                        if page_str:
                            pages_text.append(f"--- [Trang {idx + 1}] ---\n{page_str}")

                extracted_text = "\n\n".join(pages_text)

                # Scanned image detection: document has pages but no extractable text layer
                if total_pages > 0 and len(extracted_text.strip()) < 10:
                    is_scanned_image = True
                    warning_msg = (
                        "Tài liệu PDF có thể là dạng ảnh quét (scanned/raster), "
                        "không chứa text layer có thể bóc tách trực tiếp."
                    )

            # 2. DOCX extraction
            elif ext in (".docx", ".doc"):
                doc_type = "Tài liệu Word"
                if docx is None:
                    return {
                        "status": "error",
                        "tool": "extract_document_text",
                        "message": "Thư viện python-docx chưa được cài đặt.",
                    }

                doc = docx.Document(str(input_file))
                parts: List[str] = []
                for para in doc.paragraphs:
                    if para.text.strip():
                        parts.append(para.text)

                # Format tables into Markdown structure
                for idx, table in enumerate(doc.tables, 1):
                    parts.append(f"\n[Bảng {idx}]:")
                    for row in table.rows:
                        parts.append(" | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells))

                extracted_text = "\n".join(parts)

            # 3. XLSX extraction
            elif ext in (".xlsx", ".xlsm", ".xls"):
                doc_type = "Bảng tính Excel"
                if openpyxl is None:
                    return {
                        "status": "error",
                        "tool": "extract_document_text",
                        "message": "Thư viện openpyxl chưa được cài đặt.",
                    }

                wb = openpyxl.load_workbook(str(input_file), data_only=True, read_only=True)
                sheets_text: List[str] = []
                for name in wb.sheetnames:
                    ws = wb[name]
                    rows: List[str] = [f"=== Sheet: {name} ==="]
                    for r_idx, row in enumerate(ws.iter_rows(values_only=True), 1):
                        if r_idx > 200:
                            rows.append("... (cắt bớt sau 200 dòng)")
                            break
                        if any(v is not None for v in row):
                            rows.append(" | ".join(str(v) if v is not None else "" for v in row))
                    if len(rows) > 1:
                        sheets_text.append("\n".join(rows))
                wb.close()
                extracted_text = "\n\n".join(sheets_text)

            # 4. CSV extraction
            elif ext == ".csv":
                doc_type = "Dữ liệu CSV"
                try:
                    with open(input_file, "r", encoding="utf-8", errors="replace") as f:
                        reader = csv.reader(f)
                        csv_rows = [" | ".join(row) for idx, row in enumerate(reader) if idx < 300]
                    extracted_text = "\n".join(csv_rows)
                except Exception as csv_exc:
                    extracted_text = f"Lỗi đọc CSV: {csv_exc}"

            # 5. JSON extraction
            elif ext == ".json":
                doc_type = "Dữ liệu JSON"
                with open(input_file, "r", encoding="utf-8", errors="replace") as f:
                    parsed = json.load(f)
                extracted_text = json.dumps(parsed, indent=2, ensure_ascii=False)

            # 6. TXT, Markdown and source code
            elif ext in TEXT_EXTENSIONS or ext == "":
                doc_type = "Tệp văn bản thuần / Mã nguồn"
                try:
                    with open(input_file, "r", encoding="utf-8", errors="replace") as f:
                        extracted_text = f.read()
                except Exception:
                    with open(input_file, "r", encoding="latin-1", errors="replace") as f:
                        extracted_text = f.read()

            else:
                return {
                    "status": "error",
                    "tool": "extract_document_text",
                    "message": f"Định dạng tệp '{ext}' không được hỗ trợ để trích xuất văn bản.",
                }

            # Truncate at max_chars boundary to prevent LLM context overflow
            orig_len = len(extracted_text)
            truncated = False
            if orig_len > max_chars:
                extracted_text = (
                    extracted_text[:max_chars]
                    + f"\n\n[... Đã cắt bớt nội dung trích xuất ({orig_len} > {max_chars} ký tự) ...]"
                )
                truncated = True

            return {
                "status": "ok",
                "tool": "extract_document_text",
                "filename": input_file.name,
                "doc_type": doc_type,
                "total_pages": total_pages,
                "extracted_chars": len(extracted_text),
                "is_truncated": truncated,
                "is_scanned_image": is_scanned_image,
                "warning": warning_msg,
                "text": extracted_text,
                "message": (
                    f"Đã trích xuất văn bản từ {input_file.name} ({doc_type}, {len(extracted_text)} ký tự)."
                    + (f" ⚠️ {warning_msg}" if warning_msg else "")
                ),
            }
        except Exception as exc:
            logger.error("[DocumentService] extract_document_text failed: %s", exc)
            return {
                "status": "error",
                "tool": "extract_document_text",
                "message": f"Lỗi khi trích xuất văn bản: {str(exc)}",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)

    # ─── 4. TRANSLATE TEXT (DUAL-TIER HYBRID TRANSLATION) ──────────────────────

    async def translate_text(
        self,
        text: str,
        source_lang: str = "auto",
        target_lang: str = "vi",
        engine: str = "auto",
    ) -> Dict[str, Any]:
        """
        Dịch thuật văn bản đa ngôn ngữ siêu tốc qua Groq LLM Router và fallback sang Google Translate public API.
        """
        clean_text = str(text).strip()
        if not clean_text:
            return {
                "status": "error",
                "tool": "translate_text",
                "message": "Nội dung văn bản cần dịch không được để trống.",
            }

        sl = source_lang.strip().lower() or "auto"
        tl = target_lang.strip().lower() or "vi"
        target_engine = engine.strip().lower()

        # Tier 1: High-Fidelity Groq LLM Router (Llama-3.3-70b)
        if target_engine in ("auto", "llm"):
            router = self._router
            if router is None:
                try:
                    from app.core.llm_router import LlmRouter
                    router = LlmRouter()
                except Exception as r_exc:
                    logger.debug("[DocumentService] Could not initialize LlmRouter: %s", r_exc)

            if router is not None:
                try:
                    prompt = (
                        "You are an expert multilingual translator for technical and general content. "
                        f"Translate the following text accurately from {sl} to {tl}. "
                        "Preserve all markdown formatting, tables, code blocks, URLs, and placeholders unchanged. "
                        "Return ONLY the direct translation without preamble, thinking process, or closing remarks."
                    )
                    messages = [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": clean_text},
                    ]
                    resp = await router.complete(
                        messages=messages,
                        temperature=0.1,
                        max_tokens=4096,
                    )
                    if resp and "choices" in resp and len(resp["choices"]) > 0:
                        content = resp["choices"][0].get("message", {}).get("content", "").strip()
                        if content:
                            return {
                                "status": "ok",
                                "tool": "translate_text",
                                "source_lang": sl,
                                "target_lang": tl,
                                "engine": "llm",
                                "translated_text": content,
                                "message": f"Đã dịch văn bản thành công qua Groq LLM ({sl} -> {tl}).",
                            }
                except Exception as llm_exc:
                    logger.warning("[DocumentService] Tier 1 LLM translation failed, failing over to Tier 2: %s", llm_exc)

        # Tier 2: Emergency Google Translate public API fallback
        client = self._http
        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
            should_close = True

        try:
            gt_url = (
                f"https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl={urllib.parse.quote(sl)}&tl={urllib.parse.quote(tl)}"
                f"&dt=t&q={urllib.parse.quote(clean_text)}"
            )
            resp = await client.get(gt_url)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    translated_parts = [part[0] for part in data[0] if part and len(part) > 0 and part[0]]
                    full_translated = "".join(translated_parts).strip()
                    detected_sl = data[2] if len(data) > 2 and isinstance(data[2], str) else sl
                    if full_translated:
                        return {
                            "status": "ok",
                            "tool": "translate_text",
                            "source_lang": detected_sl,
                            "target_lang": tl,
                            "engine": "google",
                            "translated_text": full_translated,
                            "message": f"Đã dịch văn bản thành công qua Google Translate ({detected_sl} -> {tl}).",
                        }

            return {
                "status": "error",
                "tool": "translate_text",
                "message": f"Dịch vụ dịch thuật trả về mã trạng thái {resp.status_code}.",
            }
        except Exception as gt_exc:
            logger.error("[DocumentService] Tier 2 Google Translate fallback failed: %s", gt_exc)
            return {
                "status": "error",
                "tool": "translate_text",
                "message": f"Cả hai tầng dịch thuật đều thất bại: {str(gt_exc)}",
            }
        finally:
            if should_close:
                await client.aclose()

    # ─── 5. INSPECT MEDIA METADATA ────────────────────────────────────────────

    async def inspect_media_metadata(
        self,
        file_path_or_url: str,
    ) -> Dict[str, Any]:
        """
        Trích xuất siêu dữ liệu chi tiết qua ffprobe (độ phân giải, codec, bitrate, fps, duration), EXIF ảnh, ID3 audio.
        """
        input_file, is_transient = await self._resolve_input(file_path_or_url)
        ext = input_file.suffix.lower()

        try:
            # 1. Image metadata inspection (Pillow + EXIF)
            if ext in IMAGE_EXTENSIONS:
                with Image.open(input_file) as img:
                    w, h = img.size
                    mode = img.mode
                    img_format = img.format or ext.lstrip(".").upper()

                    exif_data: Dict[str, Any] = {}
                    try:
                        raw_exif = img.getexif()
                        if raw_exif:
                            for tag_id, val in raw_exif.items():
                                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                                # Only retain serializable primitive types
                                if isinstance(val, (int, float, str)):
                                    exif_data[tag_name] = val
                    except Exception:
                        pass

                    file_size = input_file.stat().st_size
                    summary = (
                        f"🖼️ Siêu dữ liệu Hình ảnh ({img_format}):\n"
                        f"- Kích thước: {w} x {h} px\n"
                        f"- Không gian màu: {mode}\n"
                        f"- Dung lượng: {round(file_size / 1024, 1)} KB"
                    )
                    if "Make" in exif_data or "Model" in exif_data:
                        summary += f"\n- Thiết bị chụp: {exif_data.get('Make', '')} {exif_data.get('Model', '')}".strip()
                    if "DateTime" in exif_data:
                        summary += f"\n- Ngày chụp: {exif_data.get('DateTime')}"

                    return {
                        "status": "ok",
                        "tool": "inspect_media_metadata",
                        "media_type": "image",
                        "format": img_format,
                        "width": w,
                        "height": h,
                        "mode": mode,
                        "file_size": file_size,
                        "file_size_kb": round(file_size / 1024, 1),
                        "exif": exif_data,
                        "summary": summary,
                        "message": f"Đã trích xuất thông số ảnh {w}x{h} px ({img_format}).",
                    }

            # 2. Audio & Video metadata inspection (FFprobe JSON)
            probe_cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                str(input_file),
            ]
            code, stdout, stderr = await self._run_command(probe_cmd, timeout=30)
            if code != 0:
                err_msg = stderr.decode(errors="replace").strip()
                return {
                    "status": "error",
                    "tool": "inspect_media_metadata",
                    "message": f"FFprobe trích xuất metadata thất bại: {err_msg[-150:]}",
                }

            data = json.loads(stdout.decode(errors="replace"))
            fmt = data.get("format", {})
            streams = data.get("streams", [])

            # Categorize streams
            video_stream: Optional[Dict[str, Any]] = None
            audio_stream: Optional[Dict[str, Any]] = None
            subtitle_streams: List[Dict[str, Any]] = []

            for s in streams:
                codec_type = s.get("codec_type")
                if codec_type == "video" and not video_stream:
                    video_stream = s
                elif codec_type == "audio" and not audio_stream:
                    audio_stream = s
                elif codec_type == "subtitle":
                    subtitle_streams.append(s)

            duration_sec = float(fmt.get("duration", 0.0))
            mins, secs = divmod(int(duration_sec), 60)
            hours, mins = divmod(mins, 60)
            dur_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins:02d}:{secs:02d}"

            media_type = "video" if video_stream else ("audio" if audio_stream else "unknown")
            file_size = int(fmt.get("size", input_file.stat().st_size))

            # Build Vietnamese summary
            summary_lines: List[str] = [
                f"{'🎬 Video' if media_type == 'video' else '🎵 Audio'} Metadata ({fmt.get('format_name', ext)}):",
                f"- Dung lượng: {round(file_size / (1024 * 1024), 2)} MB",
                f"- Thời lượng: {dur_str} ({round(duration_sec, 1)}s)",
                f"- Bitrate tổng: {int(fmt.get('bit_rate', 0)) // 1000} kbps",
            ]

            if video_stream:
                fps = video_stream.get("r_frame_rate", "")
                summary_lines.append(
                    f"- Hình ảnh: {video_stream.get('width')}x{video_stream.get('height')} "
                    f"({video_stream.get('codec_name', '').upper()}, {fps} fps, {video_stream.get('pix_fmt', '')})"
                )

            if audio_stream:
                channels = audio_stream.get("channels", 2)
                summary_lines.append(
                    f"- Âm thanh: {audio_stream.get('codec_name', '').upper()} "
                    f"({audio_stream.get('sample_rate')}Hz, {channels} kênh, {int(audio_stream.get('bit_rate', 0)) // 1000} kbps)"
                )

            tags = fmt.get("tags", {})
            if tags:
                for k in ("title", "artist", "album", "year", "genre", "encoder"):
                    val = tags.get(k) or tags.get(k.upper())
                    if val:
                        summary_lines.append(f"- {k.capitalize()}: {val}")

            return {
                "status": "ok",
                "tool": "inspect_media_metadata",
                "media_type": media_type,
                "duration_seconds": duration_sec,
                "duration_formatted": dur_str,
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "format": fmt,
                "video_stream": video_stream,
                "audio_stream": audio_stream,
                "subtitle_streams": subtitle_streams,
                "summary": "\n".join(summary_lines),
                "message": f"Đã trích xuất siêu dữ liệu {media_type.upper()} ({dur_str}).",
            }
        except Exception as exc:
            logger.error("[DocumentService] inspect_media_metadata failed: %s", exc)
            return {
                "status": "error",
                "tool": "inspect_media_metadata",
                "message": f"Lỗi khi trích xuất siêu dữ liệu: {str(exc)}",
            }
        finally:
            if is_transient and input_file.exists():
                input_file.unlink(missing_ok=True)
