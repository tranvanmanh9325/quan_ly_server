"""
media_download.py — High-Throughput Direct Server Download & Metadata Router.

Fortified with:
  - In-Memory Token Bucket Rate Limiter & Anti-Bruteforce IP Jail (app.core.rate_limiter).
  - OWASP 'X-Content-Type-Options: nosniff' header protection.
  - Native HTTP 206 Partial Content byte-range support.
  - Cryptographic token TTL validation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional
import urllib.parse

from fastapi import APIRouter, HTTPException, Query, Request, status
from starlette.responses import FileResponse, JSONResponse

from app.core.rate_limiter import download_guard
from app.services.media_storage_manager import media_storage_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai/media", tags=["Media Download"])


@router.get(
    "/download/{token}",
    summary="Download media file via secure token",
    response_description="Direct video stream with HTTP 206 Partial Content support",
)
@router.get(
    "/download/{token}/{filename}",
    summary="Download media file via secure token with semantic filename",
    response_description="Direct video stream with HTTP 206 Partial Content support",
)
async def download_media_file(
    request: Request,
    token: str,
    filename: Optional[str] = None,
):
    """
    Serves a published media file using Starlette FileResponse:
      - Layer 1: In-Memory Token Bucket Rate Limiter & Anti-Bruteforce IP Jail.
      - Layer 2: Validates cryptographic token and verifies TTL on-access.
      - Layer 3: Native HTTP 206 Partial Content for byte-range requests.
      - Layer 4: OWASP Security Headers (X-Content-Type-Options: nosniff).
    """
    # 1. Rate Limit & Anti-Bruteforce Jail Check
    client_ip = download_guard.check_rate_limit(request)

    try:
        file_path, metadata = media_storage_manager.get_download_file(token)
        # Success: register successful attempt to lower fail counter
        download_guard.record_successful_attempt(client_ip)
    except FileNotFoundError as exc:
        # Failure: penalize IP attempt to defend against token scanning
        download_guard.record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("[MediaDownload] Unexpected error serving token %s: %s", token, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to serve media file.",
        )

    # Ensure safe path containment within public_dir (CodeQL PathSanitizer Barrier)
    base_dir = os.path.abspath(os.path.normpath(str(media_storage_manager.public_dir)))
    safe_path = os.path.abspath(os.path.normpath(str(file_path)))
    if not safe_path.startswith(base_dir + os.sep):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Path outside base storage directory.",
        )

    # 2. Use original or requested sanitized filename for Content-Disposition
    effective_filename = metadata.get("filename") or filename or file_path.name
    headers = {
        "Cache-Control": "private, max-age=14400",
        "ngrok-skip-browser-warning": "1",
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
    }

    return FileResponse(
        path=safe_path,
        filename=effective_filename,
        media_type="video/mp4",
        content_disposition_type="attachment",
        headers=headers,
    )


@router.get(
    "/info/{token}",
    summary="Get download metadata and TTL status",
    response_model=None,
)
async def get_download_info(request: Request, token: str) -> Dict[str, Any]:
    """
    Returns public metadata and remaining validity duration for a download token.
    Protected by download_guard rate limiting.
    """
    client_ip = download_guard.check_rate_limit(request)
    try:
        file_path, metadata = media_storage_manager.get_download_file_info(token)
        download_guard.record_successful_attempt(client_ip)
    except FileNotFoundError as exc:
        download_guard.record_failed_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    base_dir = os.path.abspath(os.path.normpath(str(media_storage_manager.public_dir)))
    safe_path = os.path.abspath(os.path.normpath(str(file_path)))
    if not safe_path.startswith(base_dir + os.sep):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: Path outside base storage directory.",
        )

    import time
    now = time.time()
    expires_at = metadata.get("expires_at", 0)
    time_remaining_now = max(0, int(expires_at - now))

    return {
        "token": token,
        "title": metadata.get("title", ""),
        "filename": metadata.get("filename", file_path.name),
        "file_size": metadata.get("file_size", 0),
        "duration": metadata.get("duration", 0),
        "created_at": metadata.get("created_at", 0),
        "expires_at": expires_at,
        "time_remaining_seconds": time_remaining_now,
        "download_count": metadata.get("download_count", 0),
        "is_expired": now >= expires_at,
    }


@router.post(
    "/sweep",
    summary="Trigger immediate sweep of expired media items",
    response_model=None,
)
async def trigger_storage_sweep() -> Dict[str, Any]:
    """
    Triggers an immediate sweep of all expired public downloads and orphaned temporary files.
    """
    try:
        stats = media_storage_manager.sweep_expired()
        return {
            "status": "success",
            "message": "Storage sweep completed successfully.",
            "stats": stats,
        }
    except Exception as exc:
        logger.error("[MediaDownload] Storage sweep failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage sweep failed: {exc}",
        )
