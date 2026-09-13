"""
media_download.py — High-Throughput Direct Server Download & Metadata Router.

Exposes endpoints for streaming full-resolution videos with native HTTP 206 Range support,
enabling video seeking, multi-threaded acceleration, and download pause/resumption:
  - GET /api/ai/media/download/{token}
  - GET /api/ai/media/download/{token}/{filename}
  - GET /api/ai/media/info/{token}
  - POST /api/ai/media/sweep
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
import urllib.parse

from fastapi import APIRouter, HTTPException, Query, status
from starlette.responses import FileResponse, JSONResponse

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
    token: str,
    filename: Optional[str] = None,
):
    """
    Serves a published media file using Starlette FileResponse:
      - Validates cryptographic token and verifies TTL on-access (Layer 2 Defense).
      - Automatically supports HTTP 206 Partial Content for byte-range requests.
      - Sets media_type='video/mp4' to bypass GZipMiddleware memory buffering.
      - Includes 'ngrok-skip-browser-warning' header to prevent Ngrok interstitial landing page.
    """
    try:
        file_path, metadata = media_storage_manager.get_download_file(token)
    except FileNotFoundError as exc:
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

    # Use original or requested sanitized filename for Content-Disposition
    effective_filename = metadata.get("filename") or filename or file_path.name
    headers = {
        "Cache-Control": "private, max-age=14400",
        "ngrok-skip-browser-warning": "1",
        "Accept-Ranges": "bytes",
    }

    return FileResponse(
        path=str(file_path),
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
async def get_download_info(token: str) -> Dict[str, Any]:
    """
    Returns public metadata and remaining validity duration for a download token.
    """
    try:
        file_path, metadata = media_storage_manager.get_download_file_info(token)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    time_remaining = max(0, int(metadata.get("expires_at", 0) - metadata.get("created_at", 0)))
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
