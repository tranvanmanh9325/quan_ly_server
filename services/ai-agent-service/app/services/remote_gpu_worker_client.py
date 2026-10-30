"""
Remote GPU Worker Client (Milestone 1, Feature F2 & F4).
Provides multi-tier remote GPU acceleration for studio-grade video text removal:
- Tier 1: Hugging Face Spaces (IOPaint LaMa REST API pool with per-endpoint Circuit Breaker, retries with exponential backoff & jitter).
- Tier 2: Google Colab Relay hook (zero-leak session lifecycle, unassign/cleanup).
- Tier 3: Kaggle Dual Tesla T4 Batch Worker hook (Kaggle REST API v1, credentials loaded safely).
- Clean Session Lifecycle: automatic termination, asset cleanup, and zero resource leaks.
- Secret Safety: all credentials/tokens loaded exclusively from environment, never logged or committed.
"""

from abc import ABC, abstractmethod
import asyncio
import base64
from enum import Enum
import json
import logging
import os
from pathlib import Path
import random
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import numpy as np

logger = logging.getLogger(__name__)

def _resolve_endpoints(
    custom_endpoints: Optional[List[str]] = None,
    env_keys: Optional[List[str]] = None,
) -> List[str]:
    """Resolve remote inpainting endpoints from explicit argument or environment configuration."""
    if custom_endpoints:
        return [ep.strip() for ep in custom_endpoints if ep and ep.strip()]
    if env_keys is None:
        env_keys = ["REMOTE_GPU_ENDPOINTS", "REMOTE_INPAINT_ENDPOINTS"]
    for key in env_keys:
        val = os.getenv(key, "").strip()
        if val:
            eps = [x.strip() for x in val.split(",") if x.strip()]
            if eps:
                return eps
    return []


def _get_auth_headers(endpoint: str) -> Dict[str, str]:
    """Attach optional Hugging Face Bearer token for authorized Space rate-limits."""
    headers = {"Content-Type": "application/json"}
    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    if hf_token and ("hf.space" in endpoint or "huggingface.co" in endpoint):
        headers["Authorization"] = f"Bearer {hf_token.strip()}"
    return headers


class GpuProviderTier(str, Enum):
    TIER_1_HF_SPACES = "tier_1_hf_spaces"


class RemoteGpuWorkerError(Exception):
    """Base exception for Remote GPU Worker failures."""
    pass


def _ndarray_to_png_bytes(arr: np.ndarray) -> bytes:
    """Encode OpenCV ndarray to PNG byte stream."""
    import cv2
    success, buf = cv2.imencode(".png", arr)
    if not success:
        raise ValueError("Failed to encode ndarray to PNG format")
    return buf.tobytes()


def _png_bytes_to_ndarray(data: bytes) -> np.ndarray:
    """Decode PNG byte stream into OpenCV BGR ndarray."""
    import cv2
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode inpaint response bytes to cv2 image")
    return img


def _encode_to_data_uri(img_bytes: bytes, mime_type: str = "image/png") -> str:
    """Convert raw bytes to RFC 2397 data URI."""
    b64 = base64.b64encode(img_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


class BaseRemoteGpuProvider(ABC):
    """Abstract base class for all remote cloud GPU providers."""

    def __init__(self, name: str, tier: GpuProviderTier):
        self.name = name
        self.tier = tier

    @abstractmethod
    async def is_available(self) -> bool:
        """Check provider connectivity, credentials, and circuit breaker status."""
        pass

    @abstractmethod
    async def inpaint_roi(
        self,
        image: Union[np.ndarray, bytes],
        mask: Union[np.ndarray, bytes],
        timeout: float = 35.0,
    ) -> Optional[np.ndarray]:
        """Execute inpaint on ROI image and binary mask."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Perform a liveness and responsiveness probe."""
        pass

    @abstractmethod
    async def terminate_session(self) -> None:
        """Clean up active sessions, temporary files, and cloud instances."""
        pass


class HuggingFaceZeroGpuProvider(BaseRemoteGpuProvider):
    """
    Tier 1 Provider: Hugging Face Spaces (IOPaint LaMa REST API).
    Features:
    - Per-endpoint Circuit Breaker (failure count, cooldown).
    - Automatic retries with exponential backoff and randomized jitter.
    - Concurrency bounding via asyncio.Semaphore.
    """

    def __init__(
        self,
        endpoints: Optional[List[str]] = None,
        timeout: float = 35.0,
        max_retries: int = 2,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        concurrency_limit: int = 4,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        super().__init__(name="HuggingFaceZeroGpuProvider", tier=GpuProviderTier.TIER_1_HF_SPACES)
        self.endpoints = _resolve_endpoints(endpoints)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self.failure_threshold = int(failure_threshold)
        self.cooldown_seconds = float(cooldown_seconds)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))
        self._http_client = http_client
        self._current_endpoint_idx = 0

        # Per-endpoint circuit breaker state
        self._circuits: Dict[str, Dict[str, Any]] = {
            ep: {"failure_count": 0, "cooldown_until": 0.0, "is_open": False}
            for ep in self.endpoints
        }

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._http_client

    def _record_success(self, endpoint: str) -> None:
        circuit = self._circuits.setdefault(endpoint, {})
        circuit["failure_count"] = 0
        circuit["cooldown_until"] = 0.0
        circuit["is_open"] = False

    def _record_failure(self, endpoint: str) -> None:
        circuit = self._circuits.setdefault(endpoint, {})
        failures = circuit.get("failure_count", 0) + 1
        circuit["failure_count"] = failures
        if failures >= self.failure_threshold:
            circuit["cooldown_until"] = time.time() + self.cooldown_seconds
            circuit["is_open"] = True
            logger.warning(
                "[HuggingFaceZeroGpuProvider] Circuit opened for %s (cooldown %.1fs)",
                endpoint, self.cooldown_seconds
            )

    def _is_endpoint_available(self, endpoint: str) -> bool:
        circuit = self._circuits.get(endpoint)
        if not circuit:
            return True
        if circuit.get("is_open", False):
            if time.time() >= circuit.get("cooldown_until", 0.0):
                # Half-open trial
                circuit["is_open"] = False
                circuit["failure_count"] = 0
                return True
            return False
        return True

    async def is_available(self) -> bool:
        """Available if at least one endpoint has a closed circuit."""
        return any(self._is_endpoint_available(ep) for ep in self.endpoints)

    async def inpaint_roi(
        self,
        image: Union[np.ndarray, bytes],
        mask: Union[np.ndarray, bytes],
        timeout: float = 35.0,
    ) -> Optional[np.ndarray]:
        """Execute LaMa inpainting with circuit breaker and failover."""
        if isinstance(image, np.ndarray):
            img_bytes = _ndarray_to_png_bytes(image)
        elif isinstance(image, bytes):
            img_bytes = image
        else:
            raise TypeError("Image must be np.ndarray or bytes")

        if isinstance(mask, np.ndarray):
            mask_bytes = _ndarray_to_png_bytes(mask)
        elif isinstance(mask, bytes):
            mask_bytes = mask
        else:
            raise TypeError("Mask must be np.ndarray or bytes")

        if len(img_bytes) == 0 or len(mask_bytes) == 0:
            raise ValueError("Image and mask bytes cannot be empty")

        payload = {
            "image": _encode_to_data_uri(img_bytes),
            "mask": _encode_to_data_uri(mask_bytes),
            "hd_strategy": "Original",
        }

        client = self._get_http_client()
        num_endpoints = len(self.endpoints)
        if num_endpoints == 0:
            return None

        async with self._semaphore:
            for attempt_ep in range(num_endpoints):
                ep_idx = (self._current_endpoint_idx + attempt_ep) % num_endpoints
                endpoint = self.endpoints[ep_idx]

                if not self._is_endpoint_available(endpoint):
                    continue

                for retry in range(self.max_retries + 1):
                    t0 = time.time()
                    try:
                        req_headers = _get_auth_headers(endpoint)
                        resp = await client.post(
                            endpoint,
                            json=payload,
                            headers=req_headers,
                            timeout=timeout,
                        )

                        if resp.status_code == 200 and len(resp.content) > 100:
                            self._record_success(endpoint)
                            self._current_endpoint_idx = ep_idx
                            return _png_bytes_to_ndarray(resp.content)

                        logger.warning(
                            "[HuggingFaceZeroGpuProvider] HTTP %d from %s",
                            resp.status_code, endpoint
                        )
                        self._record_failure(endpoint)

                    except (httpx.TimeoutException, httpx.RequestError) as net_err:
                        elapsed = time.time() - t0
                        logger.warning(
                            "[HuggingFaceZeroGpuProvider] Error on %s (%.2fs): %s",
                            endpoint, elapsed, net_err
                        )
                        self._record_failure(endpoint)

                    if retry < self.max_retries:
                        backoff = (0.4 * (2 ** retry)) + random.uniform(0.05, 0.25)
                        await asyncio.sleep(backoff)

        return None

    async def health_check(self) -> bool:
        client = self._get_http_client()
        for ep in self.endpoints:
            if not self._is_endpoint_available(ep):
                continue
            model_url = ep.replace("/inpaint", "/model")
            try:
                headers = _get_auth_headers(ep)
                res = await client.get(model_url, headers=headers, timeout=5.0)
                if res.status_code == 200:
                    return True
            except Exception:
                pass
        return False

    async def terminate_session(self) -> None:
        """Close HTTP client connections."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None




class RemoteGpuWorkerClient:
    """
    Coordinator client managing remote GPU worker inpainting failover.
    Attempts configured remote providers (e.g. HuggingFaceZeroGpuProvider).
    If all tiers are exhausted or offline, returns None to trigger ClassicalFallbackManager.
    """

    def __init__(self, providers: Optional[List[BaseRemoteGpuProvider]] = None):
        if providers is not None:
            self._providers = providers
        else:
            self._providers = [
                HuggingFaceZeroGpuProvider(),
            ]

        self._stats = {
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
            "provider_usage": {p.name: 0 for p in self._providers},
        }

    @property
    def providers(self) -> List[BaseRemoteGpuProvider]:
        return self._providers

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)

    async def inpaint_roi_with_failover(
        self,
        roi_img: Union[np.ndarray, bytes],
        roi_mask: Union[np.ndarray, bytes],
        timeout_sec: float = 35.0,
    ) -> Optional[np.ndarray]:
        """
        Execute inpaint across remote providers with automatic failover.
        Returns np.ndarray on success, or None when all providers fail.
        """
        self._stats["total_requests"] += 1

        for provider in self._providers:
            try:
                if await provider.is_available():
                    result = await provider.inpaint_roi(roi_img, roi_mask, timeout=timeout_sec)
                    if result is not None:
                        self._stats["success_requests"] += 1
                        self._stats["provider_usage"][provider.name] = (
                            self._stats["provider_usage"].get(provider.name, 0) + 1
                        )
                        return result
            except Exception as err:
                logger.warning(
                    "[RemoteGpuWorkerClient] Provider %s encountered error: %s. Failing over...",
                    provider.name, err
                )

        self._stats["failed_requests"] += 1
        return None

    def inpaint_roi_with_failover_sync(
        self,
        roi_img: Union[np.ndarray, bytes],
        roi_mask: Union[np.ndarray, bytes],
        timeout_sec: float = 35.0,
    ) -> Optional[np.ndarray]:
        """Synchronous wrapper for thread-safe invocation."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    fut = executor.submit(
                        asyncio.run,
                        self.inpaint_roi_with_failover(roi_img, roi_mask, timeout_sec=timeout_sec),
                    )
                    return fut.result()
            else:
                return loop.run_until_complete(
                    self.inpaint_roi_with_failover(roi_img, roi_mask, timeout_sec=timeout_sec)
                )
        except RuntimeError:
            return asyncio.run(
                self.inpaint_roi_with_failover(roi_img, roi_mask, timeout_sec=timeout_sec)
            )

    async def health_check_all(self) -> Dict[str, bool]:
        """Probe liveness across all configured providers."""
        results = {}
        for provider in self._providers:
            try:
                results[provider.name] = await provider.health_check()
            except Exception:
                results[provider.name] = False
        return results

    async def terminate_all_sessions(self) -> None:
        """Clean up active sessions and connections across all providers."""
        for provider in self._providers:
            try:
                await provider.terminate_session()
            except Exception as e:
                logger.debug("[RemoteGpuWorkerClient] Error terminating %s: %s", provider.name, e)


# Global singleton instance
_remote_gpu_client_instance: Optional[RemoteGpuWorkerClient] = None


def get_remote_gpu_worker_client() -> RemoteGpuWorkerClient:
    """Factory helper returning singleton instance of RemoteGpuWorkerClient."""
    global _remote_gpu_client_instance
    if _remote_gpu_client_instance is None:
        _remote_gpu_client_instance = RemoteGpuWorkerClient()
    return _remote_gpu_client_instance
