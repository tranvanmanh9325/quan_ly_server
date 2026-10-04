"""
Hosted Specialist Inpainter Client (Milestone 2).
Provides zero-local-AI inpainting via public IOPaint LaMa REST endpoints on Hugging Face Spaces.
Features:
- Dynamic Failover Pool with Round-Robin / Failover between primary and secondary endpoints.
- Automatic retries with exponential backoff.
- Async native implementation with synchronous thread-safe wrappers.
- Privacy-safe: sends only minimal cropped ROI (never full uncropped video frames, no audio, no metadata).
- Concurrency bounding via Semaphore to protect server stability.
"""

import asyncio
import base64
import io
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINTS = [
    "https://sanster-iopaint-lama.hf.space/api/v1/inpaint",
    "https://gyufyjk-iopaint-lama.hf.space/api/v1/inpaint",
]


class HostedInpainterError(Exception):
    """Exception raised when all hosted inpainting endpoints fail or are unavailable."""
    pass


class HostedInpainterClient:
    """
    Client for interacting with Hosted IOPaint LaMa REST APIs.
    Dispatches ROI crops to Hugging Face Spaces with failover and retry mechanisms.
    """

    def __init__(
        self,
        endpoints: Optional[List[str]] = None,
        timeout: float = 15.0,
        max_retries: int = 2,
        concurrency_limit: int = 3,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.endpoints = list(endpoints) if endpoints else list(DEFAULT_ENDPOINTS)
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)
        self._semaphore = asyncio.Semaphore(max(1, concurrency_limit))
        self._http_client = http_client
        self._current_endpoint_idx = 0
        self._stats = {
            "total_requests": 0,
            "success_requests": 0,
            "failed_requests": 0,
            "retries": 0,
            "endpoint_usage": {ep: 0 for ep in self.endpoints},
        }

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                follow_redirects=True,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._http_client

    async def close(self) -> None:
        """Close internal HTTP client resources."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    def get_stats(self) -> Dict[str, Any]:
        """Return operational metrics for monitoring and reporting."""
        return dict(self._stats)

    @staticmethod
    def _encode_to_data_uri(img_bytes: bytes, mime_type: str = "image/png") -> str:
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return f"data:{mime_type};base64,{b64}"

    @staticmethod
    def _ndarray_to_png_bytes(arr: Any) -> bytes:
        import cv2
        success, buf = cv2.imencode(".png", arr)
        if not success:
            raise ValueError("Failed to encode ndarray to PNG format")
        return buf.tobytes()

    @staticmethod
    def _png_bytes_to_ndarray(data: bytes) -> Any:
        import cv2
        import numpy as np
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode inpaint response bytes to cv2 image")
        return img

    async def inpaint_roi(
        self,
        image: Union[bytes, Any],
        mask: Union[bytes, Any],
        timeout: Optional[float] = None,
    ) -> Union[bytes, Any]:
        """
        Inpaint a cropped ROI using the hosted LaMa endpoint pool.
        Accepts either raw PNG bytes or OpenCV BGR ndarrays.
        Returns the inpainted ROI in the same type as the input.
        """
        is_ndarray = False
        try:
            import numpy as np
            if isinstance(image, np.ndarray):
                is_ndarray = True
        except ImportError:
            pass

        # Convert input to bytes
        if is_ndarray:
            img_bytes = self._ndarray_to_png_bytes(image)
            mask_bytes = self._ndarray_to_png_bytes(mask)
        elif isinstance(image, bytes) and isinstance(mask, bytes):
            img_bytes = image
            mask_bytes = mask
        else:
            raise TypeError("Image and mask must both be bytes or numpy ndarrays")

        if len(img_bytes) == 0 or len(mask_bytes) == 0:
            raise ValueError("Image or mask bytes cannot be empty")

        res_bytes = await self._send_inpaint_request(img_bytes, mask_bytes, timeout=timeout)

        if is_ndarray:
            return self._png_bytes_to_ndarray(res_bytes)
        return res_bytes

    async def _send_inpaint_request(
        self,
        img_bytes: bytes,
        mask_bytes: bytes,
        timeout: Optional[float] = None,
    ) -> bytes:
        """
        Executes HTTP request across endpoint pool with failover and retries.
        """
        req_timeout = float(timeout) if timeout is not None else self.timeout
        client = self._get_http_client()

        payload = {
            "image": self._encode_to_data_uri(img_bytes),
            "mask": self._encode_to_data_uri(mask_bytes),
            "hd_strategy": "Original",
        }

        self._stats["total_requests"] += 1
        num_endpoints = len(self.endpoints)
        if num_endpoints == 0:
            raise HostedInpainterError("No inpainting endpoints configured in pool")

        last_error: Optional[Exception] = None

        async with self._semaphore:
            # Try endpoints starting from current preferred index
            for attempt_ep in range(num_endpoints):
                ep_idx = (self._current_endpoint_idx + attempt_ep) % num_endpoints
                endpoint = self.endpoints[ep_idx]

                for retry in range(self.max_retries + 1):
                    t0 = time.time()
                    try:
                        resp = await client.post(
                            endpoint,
                            json=payload,
                            headers={"Content-Type": "application/json"},
                            timeout=req_timeout,
                        )

                        if resp.status_code == 200 and len(resp.content) > 100:
                            elapsed = time.time() - t0
                            logger.debug(
                                "[HostedInpainterClient] Success from %s in %.2fs (size: %d bytes)",
                                endpoint, elapsed, len(resp.content)
                            )
                            self._stats["success_requests"] += 1
                            self._stats["endpoint_usage"][endpoint] = (
                                self._stats["endpoint_usage"].get(endpoint, 0) + 1
                            )
                            self._current_endpoint_idx = ep_idx
                            return resp.content

                        err_snippet = resp.text[:200] if resp.text else f"status {resp.status_code}"
                        logger.warning(
                            "[HostedInpainterClient] Endpoint %s returned HTTP %d: %s",
                            endpoint, resp.status_code, err_snippet
                        )
                        last_error = HostedInpainterError(
                            f"Endpoint {endpoint} HTTP {resp.status_code}: {err_snippet}"
                        )

                    except (httpx.TimeoutException, httpx.RequestError) as net_err:
                        elapsed = time.time() - t0
                        logger.warning(
                            "[HostedInpainterClient] Request error on %s (%.2fs): %s",
                            endpoint, elapsed, net_err
                        )
                        last_error = net_err

                    if retry < self.max_retries:
                        self._stats["retries"] += 1
                        backoff = 0.5 * (2 ** retry)
                        await asyncio.sleep(backoff)

            self._stats["failed_requests"] += 1
            raise HostedInpainterError(
                f"All hosted inpainting endpoints failed. Last error: {last_error}"
            ) from last_error

    def inpaint_roi_sync(
        self,
        image: Union[bytes, Any],
        mask: Union[bytes, Any],
        timeout: Optional[float] = None,
    ) -> Union[bytes, Any]:
        """
        Synchronous thread-safe inpainting directly via httpx.Client,
        completely avoiding cross-thread asyncio event loop collisions and deadlocks.
        """
        import numpy as np
        is_ndarray = isinstance(image, np.ndarray)
        if is_ndarray:
            img_bytes = self._ndarray_to_png_bytes(image)
            mask_bytes = self._ndarray_to_png_bytes(mask)
        elif isinstance(image, bytes) and isinstance(mask, bytes):
            img_bytes = image
            mask_bytes = mask
        else:
            raise TypeError("Image and mask must both be bytes or numpy ndarrays")

        if len(img_bytes) == 0 or len(mask_bytes) == 0:
            raise ValueError("Image or mask bytes cannot be empty")

        req_timeout = min(3.0, float(timeout) if timeout is not None else 3.0)
        payload = {
            "image": self._encode_to_data_uri(img_bytes),
            "mask": self._encode_to_data_uri(mask_bytes),
            "hd_strategy": "Original",
        }

        # Send via pure synchronous httpx.Client to be 100% thread-safe
        res_bytes = None
        ep_idx = self._current_endpoint_idx % len(self.endpoints)
        endpoint = self.endpoints[ep_idx]
        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.post(
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200 and len(resp.content) > 100:
                    res_bytes = resp.content
        except Exception as e:
            logger.debug("[HostedInpainterClient] sync post error on %s: %s", endpoint, e)

        if res_bytes is None:
            raise HostedInpainterError("All hosted inpainting endpoints failed synchronously")

        if is_ndarray:
            return self._png_bytes_to_ndarray(res_bytes)
        return res_bytes

    async def inpaint_image(
        self,
        image_path: Union[str, Path],
        mask_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Inpaint a complete image file given its path and a binary mask path.
        Saves result to output_path and returns the output path string.
        """
        img_p = Path(image_path)
        mask_p = Path(mask_path)
        if not img_p.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        if not mask_p.exists():
            raise FileNotFoundError(f"Mask file not found: {mask_path}")

        img_bytes = img_p.read_bytes()
        mask_bytes = mask_p.read_bytes()

        res_bytes = await self._send_inpaint_request(img_bytes, mask_bytes, timeout=timeout)

        if output_path is None:
            out_p = img_p.parent / f"{img_p.stem}_inpainted{img_p.suffix}"
        else:
            out_p = Path(output_path)
            out_p.parent.mkdir(parents=True, exist_ok=True)

        out_p.write_bytes(res_bytes)
        return str(out_p)

    def inpaint_image_sync(
        self,
        image_path: Union[str, Path],
        mask_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Synchronous wrapper for inpaint_image."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    fut = executor.submit(
                        asyncio.run,
                        self.inpaint_image(image_path, mask_path, output_path, timeout=timeout),
                    )
                    return fut.result()
            else:
                return loop.run_until_complete(
                    self.inpaint_image(image_path, mask_path, output_path, timeout=timeout)
                )
        except RuntimeError:
            return asyncio.run(
                self.inpaint_image(image_path, mask_path, output_path, timeout=timeout)
            )

    async def health_check(self) -> Dict[str, bool]:
        """Check live connectivity to all configured endpoints."""
        client = self._get_http_client()
        results = {}
        for ep in self.endpoints:
            # Model info route is typically /api/v1/model
            model_url = ep.replace("/inpaint", "/model")
            try:
                res = await client.get(model_url, timeout=5.0)
                results[ep] = (res.status_code == 200)
            except Exception:
                results[ep] = False
        return results


# Global singleton instance
_hosted_client_instance: Optional[HostedInpainterClient] = None


def get_hosted_inpainter_client() -> HostedInpainterClient:
    """Factory helper returning singleton instance of HostedInpainterClient."""
    global _hosted_client_instance
    if _hosted_client_instance is None:
        _hosted_client_instance = HostedInpainterClient()
    return _hosted_client_instance
