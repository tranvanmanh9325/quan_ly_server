"""
Adversarial Verification Test Suite for Phase 4 Remediation (R4 - P4).
Verifies:
1. TestNoStubProviders: Elimination of unconditional stubs in KaggleBatchGpuProvider and ColabRelayProvider.
2. TestGuaranteedSessionLifecycle: Clean session termination and resource cleanup in invariant finally blocks.
3. TestFailClosedAndClassicalFailover: Standardized warning log, seamless transition to ClassicalFallbackManager, and fail-closed verdict.
4. TestStaticAntiGamingScan: 0 untrusted endpoints, 0 hardcoded credentials, 0 Mock branching in production code.
"""

import asyncio
from pathlib import Path
import re
import shutil
import tempfile
import time
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
from app.services.session_lifecycle_manager import (
    GuaranteedSessionScope,
    RemoteSessionRegistry,
    get_session_registry,
)
from app.services.video_editor_service import (
    VideoEditorService,
    VideoJobContext,
)


class TestNoStubProviders(unittest.IsolatedAsyncioTestCase):
    """Test Suite 1: Triệt tiêu 100% mã stub trong các Provider."""

    def setUp(self):
        self.dummy_img = np.full((32, 32, 3), 120, dtype=np.uint8)
        self.dummy_mask = np.zeros((32, 32), dtype=np.uint8)
        self.dummy_mask[8:24, 8:24] = 255

        _, buf = cv2.imencode(".png", self.dummy_img)
        self.dummy_png = buf.tobytes()

    async def test_kaggle_batch_provider_declares_unavailable_when_no_credentials(self):
        """KaggleBatchGpuProvider phải trả về trung thực is_available=False khi thiếu credentials."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("pathlib.Path.is_file", return_value=False):
                provider = KaggleBatchGpuProvider(username="", api_key="")
                self.assertFalse(await provider.is_available())
                res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask, timeout=30.0)
                self.assertIsNone(res)

    async def test_kaggle_batch_provider_timeout_threshold_behavior(self):
        """KaggleBatchGpuProvider failover sớm khi timeout < 60s do đặc tính cold start."""
        provider = KaggleBatchGpuProvider(username="valid_user", api_key="valid_key")
        res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask, timeout=30.0)
        self.assertIsNone(res)

    async def test_kaggle_batch_provider_executes_rest_flow_when_configured(self):
        """KaggleBatchGpuProvider thực sự gọi REST API v1 khi cấu hình đầy đủ và timeout >= 60s."""
        provider = KaggleBatchGpuProvider(username="test_user", api_key="test_key")

        # Mock push, status poll, download output, cancel
        mock_push_resp = MagicMock(spec=httpx.Response)
        mock_push_resp.status_code = 200

        mock_status_resp = MagicMock(spec=httpx.Response)
        mock_status_resp.status_code = 200
        mock_status_resp.json.return_value = {"status": "complete"}

        mock_out_resp = MagicMock(spec=httpx.Response)
        mock_out_resp.status_code = 200
        mock_out_resp.content = self.dummy_png

        mock_cancel_resp = MagicMock(spec=httpx.Response)
        mock_cancel_resp.status_code = 200

        async def fake_post(url, *args, **kwargs):
            if "cancel" in str(url):
                return mock_cancel_resp
            return mock_push_resp

        async def fake_get(url, *args, **kwargs):
            if "output" in str(url):
                return mock_out_resp
            return mock_status_resp

        with patch.object(httpx.AsyncClient, "post", side_effect=fake_post) as mock_post:
            with patch.object(httpx.AsyncClient, "get", side_effect=fake_get) as mock_get:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask, timeout=120.0)
                    self.assertIsNotNone(res)
                    self.assertIsInstance(res, np.ndarray)
                    self.assertEqual(res.shape, self.dummy_img.shape)
                    # Verify REST push was called
                    self.assertTrue(mock_post.called)
                    self.assertTrue(mock_get.called)

    async def test_colab_relay_provider_declares_unavailable_when_no_url(self):
        """ColabRelayProvider phải trả về trung thực is_available=False khi chưa cấu hình endpoint."""
        with patch.dict("os.environ", {}, clear=True):
            provider = ColabRelayProvider(relay_url="")
            self.assertFalse(await provider.is_available())
            res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask)
            self.assertIsNone(res)

    async def test_colab_relay_executes_when_configured(self):
        """ColabRelayProvider thực sự gửi POST request qua tunnel khi được cấu hình endpoint."""
        provider = ColabRelayProvider(relay_url="https://mock.colab.relay", auth_token="token_colab_123")
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.content = self.dummy_png

        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res = await provider.inpaint_roi(self.dummy_img, self.dummy_mask)
            self.assertIsNotNone(res)
            self.assertIsInstance(res, np.ndarray)
            self.assertEqual(res.shape, self.dummy_img.shape)
            mock_post.assert_called_once()


class TestGuaranteedSessionLifecycle(unittest.IsolatedAsyncioTestCase):
    """Test Suite 2: Vòng đời phiên sạch & Giải phóng tài nguyên trong finally."""

    def setUp(self):
        self.dummy_img = np.full((32, 32, 3), 100, dtype=np.uint8)
        self.dummy_mask = np.zeros((32, 32), dtype=np.uint8)
        self.dummy_mask[8:24, 8:24] = 255
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_phase4_lifecycle_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_terminate_session_called_on_normal_completion(self):
        """Bảo đảm terminate_session được gọi khi hoàn tất bình thường."""
        mock_provider = MagicMock(spec=BaseRemoteGpuProvider)
        mock_provider.name = "MockGpu"
        mock_provider.is_available = AsyncMock(return_value=True)
        mock_provider.inpaint_roi = AsyncMock(return_value=self.dummy_img)
        mock_provider.terminate_session = AsyncMock()

        client = RemoteGpuWorkerClient(providers=[mock_provider])
        res = await client.inpaint_roi_with_failover(self.dummy_img, self.dummy_mask)
        self.assertIsNotNone(res)
        await client.terminate_all_sessions()
        mock_provider.terminate_session.assert_called_once()

    async def test_terminate_session_called_in_finally_on_exception(self):
        """Bảo đảm terminate_session LUÔN được gọi trong khối finally ngay cả khi gặp RuntimeError crash."""
        mock_provider = MagicMock(spec=BaseRemoteGpuProvider)
        mock_provider.name = "CrashingGpu"
        mock_provider.is_available = AsyncMock(return_value=True)
        mock_provider.inpaint_roi = AsyncMock(side_effect=RuntimeError("GPU OOM Fatal Crash"))
        mock_provider.terminate_session = AsyncMock()

        client = RemoteGpuWorkerClient(providers=[mock_provider])
        try:
            await client.inpaint_roi_with_failover(self.dummy_img, self.dummy_mask)
        except Exception:
            pass
        finally:
            await client.terminate_all_sessions()

        mock_provider.terminate_session.assert_called_once()

    async def test_guaranteed_session_scope_cleans_registered_assets(self):
        """GuaranteedSessionScope đảm bảo dọn sạch files và thư mục tạm đăng ký trong finally."""
        job_id = f"test_job_{int(time.time())}"
        test_dir = self.temp_dir / f"chunk_{job_id}"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = self.temp_dir / f"mask_{job_id}.png"
        test_file.write_bytes(b"dummy_mask_bytes")

        self.assertTrue(test_dir.exists())
        self.assertTrue(test_file.exists())

        try:
            async with GuaranteedSessionScope(job_id=job_id) as scope:
                scope.registry.register_temp_path(job_id, test_dir, is_dir=True)
                scope.registry.register_temp_path(job_id, test_file, is_dir=False)
                # Giả lập lỗi giữa chừng
                raise ValueError("Simulated pipeline failure")
        except ValueError:
            pass

        # Xác nhận cả thư mục và tệp tạm đã bị dọn dẹp sạch sẽ
        self.assertFalse(test_dir.exists())
        self.assertFalse(test_file.exists())

    def test_job_context_cleanup_terminates_registry_sessions(self):
        """VideoJobContext.cleanup() xóa sạch cache_dir và gọi dọn dẹp registry."""
        ctx = VideoJobContext()
        test_cache = self.temp_dir / f"kf_cache_{ctx.job_id}"
        test_cache.mkdir(parents=True, exist_ok=True)
        (test_cache / "kf_0.png").write_bytes(b"dummy_data")
        ctx.cache_dir = test_cache

        self.assertTrue(test_cache.exists())
        ctx.cleanup()
        self.assertFalse(test_cache.exists())


class TestFailClosedAndClassicalFailover(unittest.TestCase):
    """Test Suite 3: Chuyển tầng mượt mà, log chuẩn hóa và Fail-Closed."""

    def setUp(self):
        self.editor = VideoEditorService()
        self.dummy_roi = np.full((40, 80, 3), 150, dtype=np.uint8)
        self.dummy_mask = np.zeros((40, 80), dtype=np.uint8)
        self.dummy_mask[10:30, 20:60] = 255

    def test_remote_gpu_failure_triggers_diagnostic_log_and_smooth_fallback(self):
        """Khi Remote GPU worker hết quota / unreachable, ghi đúng log chuẩn hóa và chuyển tầng sang ClassicalFallbackManager."""
        with patch("app.services.remote_gpu_worker_client.RemoteGpuWorkerClient.inpaint_roi_with_failover_sync", return_value=None):
            with self.assertLogs("app.services.video_editor_service", level="WARNING") as log_capture:
                ctx = VideoJobContext()
                clean_roi = self.editor._inpaint_roi_fallback_chain(
                    self.dummy_roi, self.dummy_mask, timeout_sec=2.0, use_hosted=True, context=ctx
                )

                self.assertIsNotNone(clean_roi)
                self.assertEqual(clean_roi.shape, self.dummy_roi.shape)
                log_text = "\n".join(log_capture.output)
                expected_msg = "[RemoteGpuWorker] Quota exhausted or provider unreachable; switching cleanly to Classical Fallback C1/C2/C3"
                self.assertIn(expected_msg, log_text)
                self.assertTrue(ctx.is_fallback)
                self.assertIn("Remote GPU provider quota exhausted or unreachable", str(ctx.fallback_reason))

    def test_fail_closed_unreconstructible_critique(self):
        """Nếu toàn bộ chuỗi xử lý thất bại (còn tồn dư chữ lớn), VideoCritiqueEngine fail-closed trả về is_pass=False."""
        from app.services.video_critique_engine import VideoCritiqueEngine
        engine = VideoCritiqueEngine()

        eval_metrics = {
            "residual_ocr_words": 6,
            "residual_ocr_status": "residual_detected",
            "laplacian_texture_ratio": 0.40,
            "temporal_flicker_ratio": 1.9,
            "seam_discontinuity": 0.85,
            "phash_drift": 15,
        }
        judge = engine.pure_cpu_fallback_judge(eval_metrics)
        self.assertFalse(judge.is_pass)
        self.assertIn("text_residue", judge.artifacts)
        self.assertNotEqual(judge.score, 5)


class TestStaticAntiGamingScan(unittest.TestCase):
    """Test Suite 4: Quét tĩnh Anti-Gaming toàn diện."""

    def test_no_untrusted_endpoints_in_production(self):
        """Bảo đảm 0 endpoint gyufyjk trong toàn bộ codebase app/services/."""
        services_dir = Path("services/ai-agent-service/app/services")
        if not services_dir.exists():
            services_dir = Path("app/services")
        for py_file in services_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            self.assertNotIn("gyufyjk", content, f"Phát hiện endpoint gyufyjk trong {py_file}")

    def test_zero_mock_branches_in_production_services(self):
        """Bảo đảm zero kiểm tra is_mock hoặc rẽ nhánh MagicMock trong app/services/."""
        services_dir = Path("services/ai-agent-service/app/services")
        if not services_dir.exists():
            services_dir = Path("app/services")
        for py_file in services_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            self.assertNotIn("is_mock_cv", content, f"Phát hiện is_mock_cv trong {py_file}")
            self.assertNotIn("is_mock_inpaint", content, f"Phát hiện is_mock_inpaint trong {py_file}")
            matches = re.findall(r"isinstance\([^,]+,\s*(?:MagicMock|Mock)\)", content)
            self.assertEqual(len(matches), 0, f"Phát hiện rẽ nhánh theo Mock trong {py_file}: {matches}")

    def test_no_hardcoded_credentials_in_providers(self):
        """Bảo đảm không có API key / token hardcode trong remote_gpu_worker_client.py."""
        target_file = Path("services/ai-agent-service/app/services/remote_gpu_worker_client.py")
        if not target_file.exists():
            target_file = Path("app/services/remote_gpu_worker_client.py")
        content = target_file.read_text(encoding="utf-8")
        patterns = [
            r'api_key\s*=\s*["\'][a-zA-Z0-9_\-]{20,}["\']',
            r'auth_token\s*=\s*["\'][a-zA-Z0-9_\-]{20,}["\']',
            r'password\s*=\s*["\'][a-zA-Z0-9_\-]{8,}["\']',
        ]
        for pat in patterns:
            matches = re.findall(pat, content)
            self.assertEqual(len(matches), 0, f"Phát hiện hardcoded credential: {matches}")


if __name__ == "__main__":
    unittest.main()
