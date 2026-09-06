import asyncio
import time
import unittest
import sys
from pathlib import Path

# Add app parent directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.ssh_client import TunnelEndpoint, SshTunnelPool
from app.config import Settings


class TestSshTunnelPool(unittest.TestCase):
    def test_tunnel_endpoint_availability(self):
        ep = TunnelEndpoint(endpoint_id=1, host="0.tcp.ap.ngrok.io", port=25823, name="Account-1")
        now = time.time()
        
        # Fresh endpoint must be available
        self.assertTrue(ep.is_available(now))
        self.assertEqual(ep.usage_count, 0)
        self.assertEqual(ep.fail_count, 0)
        
        # Endpoint in cooldown must not be available
        ep.available_at = now + 60.0
        self.assertFalse(ep.is_available(now))
        self.assertTrue(ep.is_available(now + 61.0))
        
        # Dead endpoint must never be available
        ep.is_dead = True
        self.assertFalse(ep.is_available(now + 100.0))

    def test_pool_creation_and_least_used_rotation(self):
        async def run_test():
            endpoint_tuples = [
                ("0.tcp.ap.ngrok.io", 25823),
                ("0.tcp.ap.ngrok.io", 18974),
                ("0.tcp.ap.ngrok.io", 29819),
            ]
            pool = SshTunnelPool.from_endpoints(endpoint_tuples)
            self.assertEqual(pool.total_count, 3)
            self.assertTrue(pool.has_endpoints)
            
            # Initially all have usage_count=0
            candidates = await pool.get_candidate_endpoints()
            self.assertEqual(len(candidates), 3)
            first_choice = candidates[0]
            self.assertEqual(first_choice.port, 25823)
            
            # Simulate success on first tunnel -> usage_count becomes 1
            await pool.mark_success(first_choice)
            self.assertEqual(first_choice.usage_count, 1)
            self.assertEqual(pool.total_requests, 1)
            
            # Next candidate check: tunnels with usage_count=0 (port 18974, 29819) must come first!
            next_candidates = await pool.get_candidate_endpoints()
            self.assertEqual(next_candidates[0].port, 18974)
            self.assertEqual(next_candidates[1].port, 29819)
            self.assertEqual(next_candidates[2].port, 25823) # Least-used rotated to back!
            
            # Simulate success on second tunnel
            await pool.mark_success(next_candidates[0])
            self.assertEqual(next_candidates[0].usage_count, 1)
            
            # Now tunnel 3 (usage_count=0) must be first choice!
            third_candidates = await pool.get_candidate_endpoints()
            self.assertEqual(third_candidates[0].port, 29819)

        asyncio.run(run_test())

    def test_adaptive_cooldown_and_failover(self):
        async def run_test():
            endpoint_tuples = [
                ("0.tcp.ap.ngrok.io", 25823),
                ("0.tcp.ap.ngrok.io", 18974),
            ]
            pool = SshTunnelPool.from_endpoints(endpoint_tuples)
            
            candidates = await pool.get_candidate_endpoints()
            ep1 = candidates[0]
            
            # Simulate failure on ep1
            now_before = time.time()
            await pool.mark_failed(ep1, cooldown_seconds=60.0)
            
            self.assertEqual(ep1.fail_count, 1)
            self.assertEqual(pool.total_failovers, 1)
            # Available_at should be approximately now + 60s (+/- jitter)
            self.assertGreater(ep1.available_at, now_before + 50.0)
            self.assertFalse(ep1.is_available(time.time()))
            
            # In next round, ep2 (port 18974) must be top candidate while ep1 is in cooldown
            active_candidates = await pool.get_candidate_endpoints()
            self.assertEqual(active_candidates[0].port, 18974)
            self.assertEqual(active_candidates[1].port, 25823) # In cooldown, placed after healthy

        asyncio.run(run_test())

    def test_all_in_cooldown_fallback(self):
        async def run_test():
            endpoint_tuples = [
                ("0.tcp.ap.ngrok.io", 25823),
                ("0.tcp.ap.ngrok.io", 18974),
            ]
            pool = SshTunnelPool.from_endpoints(endpoint_tuples)
            
            # Put both in cooldown with different durations
            ep1 = pool.endpoints[0]
            ep2 = pool.endpoints[1]
            
            now = time.time()
            ep1.available_at = now + 100.0
            ep2.available_at = now + 30.0
            
            candidates = await pool.get_candidate_endpoints()
            # When all are in cooldown, ep2 (available in 30s) must come before ep1 (available in 100s)
            self.assertEqual(candidates[0].port, 18974)
            self.assertEqual(candidates[1].port, 25823)

        asyncio.run(run_test())

    def test_settings_ssh_fallback_endpoints_parsing(self):
        settings = Settings(
            SSH_HOST="192.168.0.100",
            SSH_PORT=22,
            SSH_FALLBACK_HOST="0.tcp.ap.ngrok.io",
            SSH_FALLBACK_PORT=25823,
            SSH_FALLBACK_PORT_2=18974,
            SSH_FALLBACK_PORT_3=29819,
            SSH_FALLBACK_PORT_4=29732,
            SSH_FALLBACK_PORT_5=14251,
            NGROK_SSH_TUNNELS="0.tcp.ap.ngrok.io:25823,0.tcp.ap.ngrok.io:18974,0.tcp.ap.ngrok.io:29819",
        )
        endpoints = settings.ssh_fallback_endpoints
        # Should deduplicate and return all 5 unique ports
        ports = [port for host, port in endpoints]
        self.assertIn(25823, ports)
        self.assertIn(18974, ports)
        self.assertIn(29819, ports)
        self.assertIn(29732, ports)
        self.assertIn(14251, ports)
        self.assertEqual(len(endpoints), 5)


if __name__ == "__main__":
    unittest.main()
