"""
Unit tests for HostedInpainterClient (Milestone 2).
Uses unittest.mock to mock network requests, ensuring 100% offline, deterministic, and fast CI execution.
Tests failover, retries, data conversions, error handling, and sync wrappers.
"""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import numpy as np

from app.services.hosted_inpainter_client import (
    DEFAULT_ENDPOINTS,
    HostedInpainterClient,
    HostedInpainterError,
    get_hosted_inpainter_client,
)


class TestHostedInpainterClient(unittest.IsolatedAsyncioTestCase):
    """Test suite for HostedInpainterClient."""

    def setUp(self):
        self.dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82" + b"A" * 150
        self.endpoints = [
            "https://gyufyjk-iopaint-lama.hf.space/api/v1/inpaint",
            "https://sanster-iopaint-lama.hf.space/api/v1/inpaint",
        ]
        self.client = HostedInpainterClient(endpoints=self.endpoints, timeout=5.0, max_retries=1)

    async def asyncTearDown(self):
        await self.client.close()

    def test_client_init_and_stats(self):
        """Verify initialization parameters and metrics tracking."""
        client = HostedInpainterClient(timeout=10.0, max_retries=2)
        self.assertEqual(client.endpoints, DEFAULT_ENDPOINTS)
        self.assertEqual(client.timeout, 10.0)
        self.assertEqual(client.max_retries, 2)
        stats = client.get_stats()
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["success_requests"], 0)
        self.assertIn("gyufyjk", list(stats["endpoint_usage"].keys())[0])

    async def test_inpaint_roi_bytes_success_primary(self):
        """Verify successful inpaint from primary endpoint returning bytes."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = self.dummy_png

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            result = await self.client.inpaint_roi(self.dummy_png, self.dummy_png)
            self.assertEqual(result, self.dummy_png)
            self.assertEqual(self.client.get_stats()["success_requests"], 1)
            mock_post.assert_called_once()
            call_url = mock_post.call_args[0][0]
            self.assertEqual(call_url, self.endpoints[0])

    async def test_inpaint_roi_ndarray_success(self):
        """Verify ndarray input produces ndarray output with valid shape."""
        arr_img = np.full((32, 32, 3), 120, dtype=np.uint8)
        arr_mask = np.zeros((32, 32), dtype=np.uint8)
        arr_mask[10:20, 10:20] = 255

        import cv2
        _, buf = cv2.imencode(".png", arr_img)
        fake_res_bytes = buf.tobytes()

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = fake_res_bytes

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res_arr = await self.client.inpaint_roi(arr_img, arr_mask)
            self.assertIsInstance(res_arr, np.ndarray)
            self.assertEqual(res_arr.shape, arr_img.shape)

    async def test_inpaint_failover_to_secondary_on_primary_error(self):
        """Verify automatic failover to secondary endpoint if primary fails."""
        resp_fail = MagicMock(spec=httpx.Response)
        resp_fail.status_code = 503
        resp_fail.text = "Service Unavailable"

        resp_ok = MagicMock(spec=httpx.Response)
        resp_ok.status_code = 200
        resp_ok.content = self.dummy_png

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            # Primary endpoint fails with 503 (including retry), then secondary succeeds
            mock_post.side_effect = [resp_fail, resp_fail, resp_ok]

            result = await self.client.inpaint_roi(self.dummy_png, self.dummy_png)
            self.assertEqual(result, self.dummy_png)
            self.assertEqual(self.client.get_stats()["success_requests"], 1)
            self.assertEqual(self.client.get_stats()["retries"], 1)
            # Verify secondary endpoint was called
            calls = [call[0][0] for call in mock_post.call_args_list]
            self.assertIn(self.endpoints[1], calls)

    async def test_inpaint_failover_on_network_timeout(self):
        """Verify failover when primary endpoint experiences network timeout."""
        resp_ok = MagicMock(spec=httpx.Response)
        resp_ok.status_code = 200
        resp_ok.content = self.dummy_png

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = [
                httpx.TimeoutException("Connection timed out"),
                httpx.TimeoutException("Connection timed out"),
                resp_ok,
            ]
            result = await self.client.inpaint_roi(self.dummy_png, self.dummy_png)
            self.assertEqual(result, self.dummy_png)
            self.assertEqual(self.client.get_stats()["success_requests"], 1)

    async def test_all_endpoints_fail_raises_hosted_inpainter_error(self):
        """Verify HostedInpainterError is raised when all endpoints fail."""
        resp_fail = MagicMock(spec=httpx.Response)
        resp_fail.status_code = 500
        resp_fail.text = "Internal Server Error"

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = resp_fail
            with self.assertRaises(HostedInpainterError):
                await self.client.inpaint_roi(self.dummy_png, self.dummy_png)
            self.assertEqual(self.client.get_stats()["failed_requests"], 1)

    async def test_inpaint_image_file_and_sync_wrapper(self):
        """Verify inpaint_image and inpaint_image_sync work on file paths."""
        with tempfile.TemporaryDirectory() as td:
            p_img = Path(td) / "test_in.png"
            p_mask = Path(td) / "test_mask.png"
            p_out = Path(td) / "test_out.png"

            p_img.write_bytes(self.dummy_png)
            p_mask.write_bytes(self.dummy_png)

            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 200
            mock_resp.content = self.dummy_png

            with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp
                out_path = await self.client.inpaint_image(p_img, p_mask, p_out)
                self.assertEqual(out_path, str(p_out))
                self.assertTrue(p_out.exists())
                self.assertEqual(p_out.read_bytes(), self.dummy_png)

            # Test sync wrapper
            p_out_sync = Path(td) / "test_out_sync.png"
            with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp
                out_path_sync = self.client.inpaint_image_sync(p_img, p_mask, p_out_sync)
                self.assertEqual(out_path_sync, str(p_out_sync))
                self.assertTrue(p_out_sync.exists())

    async def test_inpaint_image_missing_files_raises_filenotfound(self):
        """Verify FileNotFoundError is raised for non-existent image or mask."""
        with self.assertRaises(FileNotFoundError):
            await self.client.inpaint_image("/non/existent/image.png", "/non/existent/mask.png")

    async def test_input_validation_empty_or_wrong_types(self):
        """Verify type checking and empty checks on inpaint_roi."""
        with self.assertRaises(TypeError):
            await self.client.inpaint_roi("not_bytes", b"123")
        with self.assertRaises(ValueError):
            await self.client.inpaint_roi(b"", b"123")

    async def test_health_check(self):
        """Verify health_check probes /api/v1/model routes."""
        mock_resp_ok = MagicMock(spec=httpx.Response)
        mock_resp_ok.status_code = 200
        mock_resp_fail = MagicMock(spec=httpx.Response)
        mock_resp_fail.status_code = 502

        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_resp_ok, mock_resp_fail]
            health = await self.client.health_check()
            self.assertEqual(len(health), 2)
            self.assertTrue(health[self.endpoints[0]])
            self.assertFalse(health[self.endpoints[1]])

    async def test_inpaint_roi_batch_async(self):
        """Verify batch inpaint runs items concurrently and returns results in order."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = self.dummy_png

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            items = [(self.dummy_png, self.dummy_png), (self.dummy_png, self.dummy_png)]
            results = await self.client.inpaint_roi_batch_async(items)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], self.dummy_png)
            self.assertEqual(results[1], self.dummy_png)
            self.assertEqual(mock_post.call_count, 2)

    def test_singleton_factory(self):
        """Verify get_hosted_inpainter_client returns a valid singleton."""
        c1 = get_hosted_inpainter_client()
        c2 = get_hosted_inpainter_client()
        self.assertIs(c1, c2)
        self.assertIsInstance(c1, HostedInpainterClient)


if __name__ == "__main__":
    unittest.main()
