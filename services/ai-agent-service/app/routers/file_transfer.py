"""
file_transfer.py — High-Throughput LAN & WAN File Transfer Router.

Implements:
  - Session creation (/create) with 24h TTL, LAN/WAN dual links.
  - Zero-RAM chunked disk streaming upload (/upload/{token}) with 1MB aiofiles buffer.
  - RFC 7233 HTTP 206 Partial Content download (/download/{token}) with byte-range support.
  - Zero-Throttling for valid transfer tokens (no rate limiting on data chunks).
  - One-time delayed cleanup (30s grace) for concurrent downloaders.
  - Session metadata query (/info/{token}) and manual sweeper (/sweep).
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
import re
from typing import Any, AsyncIterator, Dict, Optional, Tuple
import urllib.parse

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.services.transfer_portal_template import (
    render_not_found_html,
    render_transfer_portal_html,
)
from app.services.transfer_qr_generator import generate_qr_png_bytes
from app.services.transfer_storage_manager import (
    TransferRecord,
    transfer_storage_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/transfer", tags=["File Transfer"])

TOKEN_REGEX = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class CreateTransferRequest(BaseModel):
    file_name: Optional[str] = Field(None, description="Optional original filename")
    mode: str = Field("upload", description="Mode: 'upload' or 'download'")
    one_time: bool = Field(False, description="Auto-purge after download completes")
    ttl_hours: int = Field(24, ge=1, le=168, description="Session TTL in hours (default 24h)")
    title: Optional[str] = Field(None, description="Human-readable title/description")


def parse_range_header(range_header: str, file_size: int) -> Tuple[int, int]:
    """
    Parses RFC 7233 Range header.
    Format: 'bytes=start-end', 'bytes=start-', 'bytes=-suffix'
    Returns (start, end) inclusive.
    Raises ValueError if range is invalid or unsatisfiable.
    """
    if not range_header or not range_header.startswith("bytes="):
        raise ValueError("Invalid Range header prefix")

    range_val = range_header[6:].strip()
    if "," in range_val:
        # Multi-range is treated as first range for single stream performance
        range_val = range_val.split(",")[0].strip()

    if not range_val:
        raise ValueError("Empty byte range")

    if range_val.startswith("-"):
        # Suffix range: bytes=-500 -> last 500 bytes
        try:
            suffix_len = int(range_val[1:])
        except ValueError as exc:
            raise ValueError("Invalid suffix byte range") from exc
        if suffix_len <= 0:
            raise ValueError("Suffix length must be positive")
        start = max(0, file_size - suffix_len)
        end = file_size - 1
    elif "-" in range_val:
        parts = range_val.split("-", 1)
        try:
            start = int(parts[0])
        except ValueError as exc:
            raise ValueError("Invalid start byte in range") from exc

        if parts[1].strip():
            try:
                end = int(parts[1])
            except ValueError as exc:
                raise ValueError("Invalid end byte in range") from exc
        else:
            end = file_size - 1
    else:
        raise ValueError("Invalid byte range format")

    if file_size <= 0:
        raise ValueError("Cannot satisfy range on empty file")

    if start < 0 or start > end or start >= file_size:
        raise ValueError(f"Range unsatisfiable: start={start}, end={end}, size={file_size}")

    end = min(end, file_size - 1)
    return start, end


async def file_chunk_generator(
    file_path: Path,
    start: int,
    end: int,
    token: str,
    one_time: bool,
    file_size: int,
    chunk_size: int = 1024 * 1024,  # 1MB buffer
) -> AsyncIterator[bytes]:
    """
    Asynchronously yields chunks from file between start and end inclusive using aiofiles.
    Schedules delayed cleanup on stream completion when one_time=True and end byte is reached.
    """
    import aiofiles

    bytes_remaining = end - start + 1
    try:
        async with aiofiles.open(file_path, "rb") as af:
            if start > 0:
                await af.seek(start)
            while bytes_remaining > 0:
                to_read = min(chunk_size, bytes_remaining)
                chunk = await af.read(to_read)
                if not chunk:
                    break
                bytes_remaining -= len(chunk)
                yield chunk
    finally:
        # If one_time session and stream completed up to the final byte, schedule 30s grace cleanup
        if one_time and end >= file_size - 1:
            logger.info("[TransferRouter] Stream completed for one_time token=%s; scheduling 30s delayed cleanup", token)
            transfer_storage_manager.schedule_delayed_cleanup(token, delay_seconds=30)


@router.post(
    "/create",
    summary="Create a new high-speed file transfer session",
    response_description="Session details with LAN & WAN transfer URLs",
)
async def create_transfer_session(payload: Optional[CreateTransferRequest] = None):
    """
    Initializes a transfer session with cryptographically secure token.
    Provides parallel LAN Gigabit and WAN Internet URLs.
    """
    req = payload or CreateTransferRequest()
    try:
        record = transfer_storage_manager.create_session(
            filename=req.file_name,
            mode=req.mode,
            one_time=req.one_time,
            ttl_hours=req.ttl_hours,
            title=req.title,
        )
    except Exception as exc:
        logger.error("[TransferRouter] Failed creating session: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create transfer session: {exc}",
        )

    _, lan_base = transfer_storage_manager.resolve_public_transfer_base_url_sync()
    upload_url = f"{lan_base}/api/ai/transfer/upload/{record.token}"
    portal_url = f"{lan_base}/api/ai/transfer/portal/{record.token}"

    return {
        "token": record.token,
        "filename": record.filename,
        "mode": record.mode,
        "state": record.state,
        "file_size": record.file_size,
        "content_type": record.content_type,
        "one_time": record.one_time,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "ttl_seconds": record.ttl_seconds,
        "lan_url": record.lan_url,
        "wan_url": record.internet_url,
        "upload_url": upload_url,
        "download_url": record.lan_url,
        "portal_url": portal_url,
    }


@router.post(
    "/upload/{token}",
    summary="Upload file to session via 1MB chunked disk streaming",
)
@router.post(
    "/{token}/upload",
    include_in_schema=False,
)
async def upload_file_to_session(
    request: Request,
    token: str,
    file: Optional[UploadFile] = File(None),
    filename: Optional[str] = Query(None),
    x_filename: Optional[str] = Header(None, alias="X-Filename"),
):
    """
    Receives file data via either multipart/form-data or direct binary request stream.
    Streams directly to disk with a fixed 1MB aiofiles buffer, maintaining O(1) RAM <= 2MB.
    """
    # Verify session exists and is ready for upload
    session = transfer_storage_manager.get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transfer session not found or already expired.",
        )

    effective_filename = (
        (file.filename if file and file.filename else None)
        or filename
        or x_filename
        or session.filename
        or "uploaded_file"
    )

    try:
        if file is not None:
            # Multipart upload stream adapter
            async def _multipart_stream() -> AsyncIterator[bytes]:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1MB chunk read
                    if not chunk:
                        break
                    yield chunk

            record = await transfer_storage_manager.save_upload_stream(
                token=token,
                filename=effective_filename,
                stream=_multipart_stream(),
            )
        else:
            # Raw binary request body stream
            record = await transfer_storage_manager.save_upload_stream(
                token=token,
                filename=effective_filename,
                stream=request.stream(),
            )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc) if isinstance(exc, FileNotFoundError) else "Invalid transfer token format.",
        )
    except Exception as exc:
        logger.error("[TransferRouter] Stream upload error for token %s: %s", token, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload processing failed: {exc}",
        )

    return {
        "status": "success",
        "message": "File uploaded successfully.",
        "record": record.to_dict(),
    }


@router.get(
    "/download/{token}",
    summary="Download transfer file with RFC 7233 HTTP 206 Partial Content support",
)
@router.get(
    "/download/{token}/{filename}",
    summary="Download transfer file with semantic filename",
)
@router.get(
    "/{token}/download",
    include_in_schema=False,
)
@router.get(
    "/file/{token}",
    include_in_schema=False,
)
@router.get(
    "/file/{token}/{filename}",
    include_in_schema=False,
)
async def download_transfer_file(
    request: Request,
    token: str,
    filename: Optional[str] = None,
):
    """
    High-throughput direct file downloader:
      - Validates cryptographic token and verifies TTL.
      - RFC 7233 Range requests: HTTP 206 Partial Content (bytes=start-end, bytes=start-, bytes=-suffix).
      - Returns HTTP 416 Range Not Satisfiable when range is invalid.
      - Zero-throttling on valid token: bypasses rate limiting for multi-threaded downloads.
      - Headers: Accept-Ranges: bytes, Cache-Control: no-cache, Content-Encoding: identity.
      - Delayed cleanup (30s grace) when one_time=True and stream reaches end.
    """
    try:
        file_path, record = transfer_storage_manager.get_download_file(token, increment_count=True)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc) if isinstance(exc, FileNotFoundError) else "Invalid transfer token format.",
        )
    except Exception as exc:
        logger.error("[TransferRouter] Unexpected error retrieving file for token %s: %s", token, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve file.",
        )

    # Path traversal safety check
    base_dir = os.path.abspath(os.path.normpath(str(transfer_storage_manager.base_dir)))
    safe_path = os.path.abspath(os.path.normpath(str(file_path)))
    if os.path.commonpath([base_dir, safe_path]) != base_dir or safe_path == base_dir:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Path outside base transfer directory.",
        )

    file_size = record.file_size
    raw_filename = filename or record.filename or file_path.name
    effective_filename = Path(raw_filename.replace("\\", "/")).name or "downloaded_file"
    quoted_filename = urllib.parse.quote(effective_filename)
    content_type = record.content_type or mimetypes.guess_type(effective_filename)[0] or "application/octet-stream"

    range_header = request.headers.get("Range")

    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Content-Encoding": "identity",
        "X-Content-Type-Options": "nosniff",
        "ngrok-skip-browser-warning": "1",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}",
    }

    if range_header:
        try:
            start, end = parse_range_header(range_header, file_size)
        except ValueError as exc:
            logger.debug("[TransferRouter] Invalid range '%s' for token %s: %s", range_header, token, exc)
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={
                    "Content-Range": f"bytes */{file_size}",
                    "Accept-Ranges": "bytes",
                },
                content=b"Requested Range Not Satisfiable",
                media_type="text/plain",
            )

        content_length = end - start + 1
        headers = dict(common_headers)
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(content_length)

        return StreamingResponse(
            file_chunk_generator(
                file_path=file_path,
                start=start,
                end=end,
                token=token,
                one_time=record.one_time,
                file_size=file_size,
            ),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=content_type,
            headers=headers,
        )

    # Full file download (200 OK)
    headers = dict(common_headers)
    headers["Content-Length"] = str(file_size)

    return StreamingResponse(
        file_chunk_generator(
            file_path=file_path,
            start=0,
            end=file_size - 1,
            token=token,
            one_time=record.one_time,
            file_size=file_size,
        ),
        status_code=status.HTTP_200_OK,
        media_type=content_type,
        headers=headers,
    )


@router.get(
    "/info/{token}",
    summary="Get transfer session metadata and TTL status",
)
@router.get(
    "/{token}/info",
    include_in_schema=False,
)
async def get_transfer_info(token: str):
    """
    Returns public metadata and remaining validity duration for a transfer session token.
    """
    session = transfer_storage_manager.get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transfer session not found or already expired.",
        )

    return session.to_dict()


@router.post(
    "/sweep",
    summary="Trigger immediate sweep of expired transfer sessions",
)
async def trigger_transfer_sweep():
    """
    Triggers an immediate sweep of all expired transfer sessions and orphaned temporary folders.
    """
    try:
        stats = transfer_storage_manager.sweep_expired()
        return {
            "status": "success",
            "message": "Transfer storage sweep completed successfully.",
            "stats": stats,
        }
    except Exception as exc:
        logger.error("[TransferRouter] Error during storage sweep: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage sweep failed: {exc}",
        )


@router.get(
    "/portal/{token}",
    summary="Web Drop Portal for high-speed file upload, download and preview",
    response_class=HTMLResponse,
)
@router.get(
    "/{token}/portal",
    include_in_schema=False,
    response_class=HTMLResponse,
)
async def get_transfer_portal(token: str):
    """
    Renders the lightweight (< 50KB, Zero-CDN) Web Drop Portal UI:
      - Upload Dropzone with drag-drop, chunked upload, dynamic % progress, instantaneous MB/s speed, ETA, cancel.
      - Download Portal with file metadata, TTL countdown, high-speed download button, copy link.
      - In-browser media preview for video (MP4/WebM with HTTP 206 seek), audio (MP3/WAV), image, and PDF.
      - Returns 404 HTMLResponse if token not found or expired.
    """
    if not token or not TOKEN_REGEX.match(token):
        html_content = render_transfer_portal_html(record=None)
        return HTMLResponse(
            content=html_content,
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="text/html",
        )

    session = transfer_storage_manager.get_session(token)
    if not session:
        html_content = render_transfer_portal_html(record=None)
        return HTMLResponse(
            content=html_content,
            status_code=status.HTTP_404_NOT_FOUND,
            media_type="text/html",
        )

    wan_url, lan_url = transfer_storage_manager.resolve_urls(session.token, session.filename)
    html_content = render_transfer_portal_html(
        record=session,
        lan_url=session.lan_url or lan_url,
        wan_url=session.internet_url or wan_url,
        token=session.token,
    )
    return HTMLResponse(
        content=html_content,
        status_code=status.HTTP_200_OK,
        media_type="text/html",
    )


@router.get(
    "/qr/{token}",
    summary="Get in-memory QR code PNG image for file transfer session",
    response_class=Response,
)
@router.get(
    "/{token}/qr",
    include_in_schema=False,
    response_class=Response,
)
async def get_transfer_qr_code(token: str):
    """
    Generates and returns an in-memory PNG QR code image pointing to the transfer portal:
      - Validates session existence and non-expiration.
      - Resolves target portal URL (prioritizing WAN internet URL for mobile device camera scans).
      - Generates PNG bytes via transfer_qr_generator directly in memory (Zero-Disk Leak).
      - Returns Response with image/png media type and HTTP 86400s Cache-Control header.
    """
    session = transfer_storage_manager.get_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transfer session not found or already expired.",
        )

    internet_base, lan_base = transfer_storage_manager.resolve_public_transfer_base_url_sync()
    base_url = internet_base if internet_base else lan_base
    target_portal_url = f"{base_url}/api/ai/transfer/portal/{session.token}"

    png_bytes = generate_qr_png_bytes(target_portal_url)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": f'inline; filename="qr_{session.token[:8]}.png"',
        },
    )


