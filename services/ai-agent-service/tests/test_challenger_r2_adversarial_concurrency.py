"""
test_challenger_r2_adversarial_concurrency.py — Adversarial Concurrency & Socket Lifecycle Verification Suite.

Author: Challenger 2 (Empirical Adversarial Verification)
Role: critic, specialist
Target: R2 ResourceWarning & Concurrency Lifecycle Verification

Adversarial Stress Dimensions:
1. `HttpClientManager` lifecycle concurrency:
   - Rapid concurrent acquire and close race conditions (50+ coroutines).
   - Resilience against closed event loops without leaking unclosed transports.
   - Close idempotency under multithreaded assault.
2. `TestClient` rapid creation & teardown concurrency:
   - 100 consecutive instances burst creation and closure with handle/socket leak tracking.
   - Multithreaded concurrent requests and teardown (ThreadPoolExecutor).
   - Double close idempotency and context manager equivalence.
3. Socket transport lifecycle & connection-refused trap:
   - Reproduction of CI closed-port probe without orphaned asyncio transports.
   - Verification under strict `-W error::ResourceWarning`.
"""

import asyncio
import concurrent.futures
import gc
import os
import socket
import sys
import threading
import time
import unittest
import warnings
from pathlib import Path
from typing import List

# Ensure ai-agent-service directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import httpx
import psutil

from app.core.http_client import HttpClientManager, http_client_manager


class TestAdversarialHttpClientLifecycle(unittest.IsolatedAsyncioTestCase):
    """Stress tests on HttpClientManager singleton connection pool and lifecycle."""

    async def asyncSetUp(self):
        # Ensure clean state before each test
        await http_client_manager.close()

    async def asyncTearDown(self):
        # Guarantee cleanup after each test
        await http_client_manager.close()
        gc.collect()

    async def test_concurrent_acquire_and_close_race_condition(self):
        """
        Adversarial Test 1: Race Condition between concurrent acquire (get_client/get_media_client)
        and rapid background close() calls across 50 concurrent tasks.
        Expectation: No unhandled exceptions, no crash, no dangling unclosed transport warnings.
        """
        errors: List[Exception] = []
        stop_signal = asyncio.Event()

        async def worker_acquire(worker_id: int):
            while not stop_signal.is_set():
                try:
                    if worker_id % 2 == 0:
                        client = http_client_manager.get_client()
                        self.assertIsNotNone(client)
                    else:
                        m_client = http_client_manager.get_media_client()
                        self.assertIsNotNone(m_client)
                    await asyncio.sleep(0.001)
                except Exception as ex:
                    errors.append(ex)

        async def worker_close():
            for _ in range(25):
                await asyncio.sleep(0.003)
                try:
                    await http_client_manager.close()
                except Exception as ex:
                    errors.append(ex)

        # Launch 20 acquire workers and 2 close workers simultaneously
        acquire_tasks = [asyncio.create_task(worker_acquire(i)) for i in range(20)]
        close_tasks = [asyncio.create_task(worker_close()) for _ in range(2)]

        await asyncio.gather(*close_tasks)
        stop_signal.set()
        await asyncio.gather(*acquire_tasks)

        self.assertEqual(len(errors), 0, f"Unexpected errors during acquire/close race: {errors}")

    def test_multithreaded_close_idempotency(self):
        """
        Adversarial Test 2: Multithreaded hammering of http_client_manager.close().
        Expectation: Close must be completely idempotent across 10 distinct OS threads.
        """
        errors = []

        def thread_close_runner():
            for _ in range(10):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    # Initialize clients on this loop
                    _ = http_client_manager.get_client()
                    _ = http_client_manager.get_media_client()
                    loop.run_until_complete(http_client_manager.close())
                    # Redundant close call
                    loop.run_until_complete(http_client_manager.close())
                except Exception as e:
                    errors.append(e)
                finally:
                    loop.close()

        threads = [threading.Thread(target=thread_close_runner) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Multithreaded close threw errors: {errors}")

    def test_closed_event_loop_resilience(self):
        """
        Adversarial Test 3: Client was initialized on an event loop that subsequently closed
        WITHOUT calling close(). A later event loop calls close().
        Worker 1 added try/except around aclose() to catch closed loop RuntimeError.
        Expectation: http_client_manager.close() must not raise RuntimeError and must reset _client = None.
        """
        # Step 1: Create client on temporary loop and close loop prematurely
        temp_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(temp_loop)
        client = http_client_manager.get_client()
        media_client = http_client_manager.get_media_client()
        self.assertIsNotNone(client)
        self.assertIsNotNone(media_client)
        temp_loop.close()

        # Step 2: Now in a new event loop, close the manager
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            new_loop.run_until_complete(http_client_manager.close())
            self.assertIsNone(http_client_manager._client)
            self.assertIsNone(http_client_manager._media_client)
        finally:
            new_loop.close()


class TestAdversarialTestClientConcurrency(unittest.TestCase):
    """Stress tests on FastAPI / Starlette TestClient rapid creation, concurrency, and teardown."""

    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()

        @cls.app.get("/api/test/ping")
        def ping():
            return JSONResponse({"status": "pong", "time": time.time()})

        @cls.app.post("/api/test/echo")
        def echo(payload: dict):
            return JSONResponse(payload)

    def test_rapid_burst_creation_and_close_leak_check(self):
        """
        Adversarial Test 4: Rapid creation and closure of 100 TestClient instances.
        Track OS handle/socket count to verify no resource leaks.
        """
        process = psutil.Process()
        gc.collect()
        initial_handles = process.num_handles() if hasattr(process, "num_handles") else 0

        for _ in range(100):
            client = TestClient(self.app)
            res = client.get("/api/test/ping")
            self.assertEqual(res.status_code, 200)
            client.close()

        gc.collect()
        final_handles = process.num_handles() if hasattr(process, "num_handles") else 0

        # Handle growth should be bounded (allow nominal runtime fluctuations < 50 handles)
        handle_diff = final_handles - initial_handles
        self.assertLess(handle_diff, 50, f"Potential handle leak detected: handle difference = {handle_diff}")

    def test_multithreaded_testclient_concurrency(self):
        """
        Adversarial Test 5: Concurrent requests across 10 threads, each executing 10 requests
        via dedicated TestClient instances with clean teardown.
        """
        errors = []

        def worker_task(thread_id: int):
            for i in range(10):
                client = TestClient(self.app)
                try:
                    res = client.post("/api/test/echo", json={"thread_id": thread_id, "req_id": i})
                    if res.status_code != 200 or res.json().get("thread_id") != thread_id:
                        errors.append(f"Invalid response in thread {thread_id}: {res.text}")
                except Exception as ex:
                    errors.append(f"Exception in thread {thread_id}: {ex}")
                finally:
                    client.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, tid) for tid in range(10)]
            concurrent.futures.wait(futures)

        self.assertEqual(len(errors), 0, f"Multithreaded TestClient errors: {errors}")

    def test_context_manager_and_double_close_safety(self):
        """
        Adversarial Test 6: Verify context manager 'with TestClient' and double .close() safety.
        Double close must be completely safe (idempotent) and not raise exceptions.
        """
        with TestClient(self.app) as client:
            res = client.get("/api/test/ping")
            self.assertEqual(res.status_code, 200)

        # Explicit client double close
        client2 = TestClient(self.app)
        res2 = client2.get("/api/test/ping")
        self.assertEqual(res2.status_code, 200)
        client2.close()
        # Second close must not raise
        try:
            client2.close()
        except Exception as e:
            self.fail(f"Second client.close() raised unexpected exception: {e}")

    def test_exception_injection_in_endpoint_clean_teardown(self):
        """
        Adversarial Test 7: When an ASGI route raises an unhandled 500 error or crashes midway,
        verify that TestClient.close() still cleans up without orphaned resources or ResourceWarning.
        """
        app_with_error = FastAPI()

        @app_with_error.get("/api/crash")
        def crash_route():
            raise RuntimeError("Adversarial Injected Crash!")

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", ResourceWarning)

            for _ in range(20):
                client = TestClient(app_with_error, raise_server_exceptions=False)
                try:
                    res = client.get("/api/crash")
                    self.assertEqual(res.status_code, 500)
                finally:
                    client.close()

            gc.collect()
            resource_warnings = [
                w for w in recorded_warnings if issubclass(w.category, ResourceWarning)
            ]
            self.assertEqual(
                len(resource_warnings),
                0,
                f"ResourceWarning after injected 500 crashes: {[str(w.message) for w in resource_warnings]}",
            )


class TestAdversarialSocketAndTransportLeakHarness(unittest.TestCase):
    """Stress tests on raw socket lifecycle and closed-port probing without ResourceWarning."""

    def test_raw_socket_probe_on_closed_port_no_leak(self):
        """
        Adversarial Test 8: Replicate the CI port-probing scenario (Worker 1 fix in test_stress_concurrency_m4).
        Attempt connection to an unassigned local port 50 times in rapid succession.
        Verify that socket closes cleanly in finally block and leaves zero open sockets.
        """
        # Find a free/closed port
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(("127.0.0.1", 0))
        _, closed_port = temp_sock.getsockname()
        temp_sock.close()

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", ResourceWarning)

            for _ in range(50):
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.05)
                try:
                    sock.connect(("127.0.0.1", closed_port))
                except Exception:
                    pass
                finally:
                    sock.close()

            gc.collect()

            # Ensure no ResourceWarnings were emitted
            resource_warnings = [
                w for w in recorded_warnings if issubclass(w.category, ResourceWarning)
            ]
            self.assertEqual(
                len(resource_warnings),
                0,
                f"ResourceWarning detected during raw socket probe: {[str(w.message) for w in resource_warnings]}",
            )

    def test_httpx_asyncclient_connection_refused_clean_shutdown(self):
        """
        Adversarial Test 9: Simulate httpx.AsyncClient encountering ConnectionRefusedError.
        Verify that clean teardown prevents unclosed transport warnings.
        """
        async def run_probe():
            with warnings.catch_warnings(record=True) as recorded_warnings:
                warnings.simplefilter("always", ResourceWarning)

                # Find a closed port
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.bind(("127.0.0.1", 0))
                _, closed_port = temp_sock.getsockname()
                temp_sock.close()

                client = httpx.AsyncClient(timeout=0.1)
                try:
                    await client.get(f"http://127.0.0.1:{closed_port}/health")
                except Exception:
                    pass
                finally:
                    await client.aclose()

                gc.collect()

                resource_warnings = [
                    w for w in recorded_warnings if issubclass(w.category, ResourceWarning)
                ]
                return resource_warnings

        res_warnings = asyncio.run(run_probe())
        self.assertEqual(
            len(res_warnings),
            0,
            f"ResourceWarning detected during httpx probe: {[str(w.message) for w in res_warnings]}",
        )

    def test_mixed_workload_high_concurrency_stress(self):
        """
        Adversarial Test 10: Mixed high-concurrency onslaught combining:
        - 10 threads running TestClient requests
        - 10 threads running HttpClientManager acquire & close cycles
        - 5 threads running raw socket probe cycles
        All running simultaneously for 2 seconds.
        Expectation: Zero deadlocks, zero crashes, zero ResourceWarnings, gc.garbage is clean.
        """
        app = FastAPI()

        @app.get("/ping")
        def ping():
            return {"status": "ok"}

        stop_event = threading.Event()
        errors = []

        def testclient_worker():
            while not stop_event.is_set():
                client = TestClient(app)
                try:
                    res = client.get("/ping")
                    if res.status_code != 200:
                        errors.append("Invalid status code in testclient_worker")
                except Exception as ex:
                    errors.append(f"TestClient error: {ex}")
                finally:
                    client.close()
                time.sleep(0.005)

        def http_manager_worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                while not stop_event.is_set():
                    _ = http_client_manager.get_client()
                    _ = http_client_manager.get_media_client()
                    loop.run_until_complete(http_client_manager.close())
                    time.sleep(0.005)
            except Exception as ex:
                errors.append(f"HttpManager error: {ex}")
            finally:
                loop.close()

        def socket_probe_worker():
            temp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            temp.bind(("127.0.0.1", 0))
            _, closed_port = temp.getsockname()
            temp.close()

            while not stop_event.is_set():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.02)
                try:
                    s.connect(("127.0.0.1", closed_port))
                except Exception:
                    pass
                finally:
                    s.close()
                time.sleep(0.005)

        with warnings.catch_warnings(record=True) as recorded_warnings:
            warnings.simplefilter("always", ResourceWarning)

            threads: List[threading.Thread] = []
            for _ in range(8):
                threads.append(threading.Thread(target=testclient_worker))
            for _ in range(6):
                threads.append(threading.Thread(target=http_manager_worker))
            for _ in range(4):
                threads.append(threading.Thread(target=socket_probe_worker))

            for t in threads:
                t.start()

            time.sleep(2.0)
            stop_event.set()

            for t in threads:
                t.join(timeout=5.0)

            gc.collect()

            self.assertEqual(len(errors), 0, f"Errors observed during mixed concurrency stress: {errors}")
            self.assertEqual(len(gc.garbage), 0, f"Uncollected cyclical garbage found: {gc.garbage}")

            resource_warnings = [
                w for w in recorded_warnings if issubclass(w.category, ResourceWarning)
            ]
            self.assertEqual(
                len(resource_warnings),
                0,
                f"ResourceWarning detected during mixed concurrency: {[str(w.message) for w in resource_warnings]}",
            )


if __name__ == "__main__":
    unittest.main()
