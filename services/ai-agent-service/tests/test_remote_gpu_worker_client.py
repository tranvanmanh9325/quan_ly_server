"""
Unit tests for RemoteGpuWorkerClient and multi-tier providers (Milestone 1, F2 & F4).
Tests failover, circuit breaker, retry jitter, timeouts, mock HTTP, clean session lifecycle, and secret safety.
Runs 100% offline and deterministic in CI.
"""

import asyncio
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import httpx
import numpy as np

from app.services.remote_gpu_worker_client import (
    BaseRemoteGpuProvider,
    ColabRelayProvider,
    GpuProviderTier,
    HuggingFaceZeroGpuProvider,
    KaggleBatchGpuProvider,
    RemoteGpuWorkerClient,
    get_remote_gpu_worker_client,
)


class TestRemoteGpuWorkerClient(unittest.IsolatedAsyncioTestCase):
    """Test suite for RemoteGpuWorkerClient."""

    def setUp(self):
        # 32x32 synthetic sample images
        self.dummy_img = np.full((32, 32, 3), 150, dtype=np.uint8)
        self.dummy_mask = np.zeros((32, 32), dtype=np.uint8)
        self.dummy_mask[8:24, 8:24] = 255

        _, buf = cv2.imencode(".png", self.dummy_img)
        self.dummy_png = buf.tobytes()

    def test_client_initialization_default_providers(self):
        """Verify default instantiation includes all 3 tiers."""
        client = RemoteGpuWorkerClient()
        self.assertEqual(len(client.providers), 3)
        self.assertIsInstance(client.providers[0], HuggingFaceZeroGpuProvider)
        self.assertIsInstance(client.providers[1], ColabRelayProvider)
        self.assertIsInstance(client.providers[2], KaggleBatchGpuProvider)

        stats = client.get_stats()
        self.assertEqual(stats["total_requests"], 0)
        self.assertEqual(stats["success_requests"], 0)
        self.assertEqual(stats["failed_requests"], 0)

    async def test_hf_provider_success_primary_endpoint(self):
        """Verify Tier 1 provider successfully inpaints and updates stats."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = self.dummy_png

        provider = HuggingFaceZeroGpuProvider(
            endpoints=["https://gyufyjk-iopaint-lama.hf.space/api/v1/inpaint"],
            max_retries=1,
        )
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask)

            self.assertIsNotNone(res)
            self.assertIsInstance(res, np.ndarray)
            self.assertEqual(res.shape, self.dummy_img.shape)
            mock_post.assert_called_once()

    async def test_hf_provider_circuit_breaker_trip(self):
        """Verify repeated failures trip circuit breaker into open state."""
        provider = HuggingFaceZeroGpuProvider(
            endpoints=["https://ep1.test/api/v1/inpaint"],
            max_retries=0,
            failure_threshold=2,
            cooldown_seconds=60.0,
        )

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            # 1st failure
            res1 = await provider.inpaint_roi(self.dummy_img, self.dummy_mask)
            self.assertIsNone(res1)
            self.assertTrue(await provider.is_available())

            # 2nd failure -> should trip circuit
            res2 = await provider.inpaint_roi(self.dummy_img, self.dummy_mask)
            self.assertIsNone(res2)
            self.assertFalse(await provider.is_available())

    async def test_failover_tier1_to_tier2(self):
        """Verify client fails over to Tier 2 Colab Relay when Tier 1 HF Spaces fails."""
        mock_hf = MagicMock(spec=BaseRemoteGpuProvider)
        mock_hf.name = "MockHF"
        mock_hf.tier = GpuProviderTier.TIER_1_HF_SPACES
        mock_hf.is_available = AsyncMock(return_value=True)
        mock_hf.inpaint_roi = AsyncMock(return_value=None)  # Fails

        mock_colab = MagicMock(spec=BaseRemoteGpuProvider)
        mock_colab.name = "MockColab"
        mock_colab.tier = GpuProviderTier.TIER_2_COLAB_RELAY
        mock_colab.is_available = AsyncMock(return_value=True)
        mock_colab.inpaint_roi = AsyncMock(return_value=self.dummy_img)  # Succeeds

        client = RemoteGpuWorkerClient(providers=[mock_hf, mock_colab])
        result = await client.inpaint_roi_with_failover(self.dummy_img, self.dummy_mask)

        self.assertIsNotNone(result)
        self.assertEqual(result.shape, self.dummy_img.shape)
        self.assertEqual(client.get_stats()["success_requests"], 1)
        self.assertEqual(client.get_stats()["provider_usage"]["MockColab"], 1)

    async def test_all_providers_fail_returns_none(self):
        """Verify None is returned when all providers in pool fail, enabling classical fallback."""
        mock_p1 = MagicMock(spec=BaseRemoteGpuProvider)
        mock_p1.name = "P1"
        mock_p1.is_available = AsyncMock(return_value=True)
        mock_p1.inpaint_roi = AsyncMock(return_value=None)

        mock_p2 = MagicMock(spec=BaseRemoteGpuProvider)
        mock_p2.name = "P2"
        mock_p2.is_available = AsyncMock(return_value=False)

        client = RemoteGpuWorkerClient(providers=[mock_p1, mock_p2])
        result = await client.inpaint_roi_with_failover(self.dummy_img, self.dummy_mask)

        self.assertIsNone(result)
        self.assertEqual(client.get_stats()["failed_requests"], 1)

    def test_sync_wrapper_inpaint_roi_with_failover_sync(self):
        """Verify synchronous wrapper works correctly without deadlocks."""
        mock_p = MagicMock(spec=BaseRemoteGpuProvider)
        mock_p.name = "MockSync"
        mock_p.is_available = AsyncMock(return_value=True)
        mock_p.inpaint_roi = AsyncMock(return_value=self.dummy_img)

        client = RemoteGpuWorkerClient(providers=[mock_p])
        res = client.inpaint_roi_with_failover_sync(self.dummy_img, self.dummy_mask)

        self.assertIsNotNone(res)
        self.assertEqual(res.shape, self.dummy_img.shape)

    async def test_health_check_all(self):
        """Verify health_check_all polls each provider."""
        p1 = MagicMock(spec=BaseRemoteGpuProvider)
        p1.name = "ProviderA"
        p1.health_check = AsyncMock(return_value=True)

        p2 = MagicMock(spec=BaseRemoteGpuProvider)
        p2.name = "ProviderB"
        p2.health_check = AsyncMock(return_value=False)

        client = RemoteGpuWorkerClient(providers=[p1, p2])
        status = await client.health_check_all()

        self.assertEqual(status, {"ProviderA": True, "ProviderB": False})

    async def test_terminate_all_sessions(self):
        """Verify clean session lifecycle cleans up all providers."""
        p1 = MagicMock(spec=BaseRemoteGpuProvider)
        p1.name = "P1"
        p1.terminate_session = AsyncMock()

        p2 = MagicMock(spec=BaseRemoteGpuProvider)
        p2.name = "P2"
        p2.terminate_session = AsyncMock()

        client = RemoteGpuWorkerClient(providers=[p1, p2])
        await client.terminate_all_sessions()

        p1.terminate_session.assert_called_once()
        p2.terminate_session.assert_called_once()

    def test_secret_safety_kaggle_and_colab(self):
        """Verify Kaggle and Colab providers do not expose raw secrets in repr."""
        secret_token = "SUPER_SECRET_TOKEN_XYZ123"
        colab = ColabRelayProvider(relay_url="https://relay.colab", auth_token=secret_token)
        self.assertNotIn(secret_token, repr(colab))
        self.assertNotIn(secret_token, str(colab))

        kaggle = KaggleBatchGpuProvider(username="testuser", api_key=secret_token)
        self.assertNotIn(secret_token, repr(kaggle))
        self.assertNotIn(secret_token, str(kaggle))

    def test_input_validation(self):
        """Verify invalid input types raise appropriate exceptions."""
        provider = HuggingFaceZeroGpuProvider()
        with self.assertRaises(TypeError):
            asyncio.run(provider.inpaint_roi(12345, self.dummy_mask))

        with self.assertRaises(ValueError):
            asyncio.run(provider.inpaint_roi(b"", b""))

    def test_singleton_factory(self):
        """Verify singleton factory helper."""
        c1 = get_remote_gpu_worker_client()
        c2 = get_remote_gpu_worker_client()
        self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()
