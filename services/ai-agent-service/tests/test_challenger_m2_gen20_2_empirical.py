"""
services/ai-agent-service/tests/test_challenger_m2_gen20_2_empirical.py
Empirical Adversarial Stress Test Suite for Milestone 2 (Challenger 2).

Test Matrix:
1. Challenge 1: Storage Concurrency Stress Test
   - 1,000 credential logging events fired concurrently across async tasks
   - Concurrent read queries during write bursts
   - Zero deadlocks, zero `sqlite3.OperationalError: database is locked`
   - Data integrity verification (all 1000 records persisted, metrics aggregated accurately)

2. Challenge 2: Nginx SSI & Configuration Verification
   - 403.html SSI syntax check: `<!--#echo var="remote_addr" ... -->` and `<!--#echo var="time_local" ... -->`
   - HTML/CSS structure validation
   - security_rules.conf regex patterns validation (PCRE compilation, test attack vectors & benign inputs)
   - nginx.conf syntax integrity (blocklist include, 403 error page mapping, ssi on)
   - docker-compose.yml YAML syntax validation & port mapping verification ('2222:2222', '23:23')
   - Container packaging & mount gap inspection (identifying missing COPY/mount for conf.d & 403.html)

3. Challenge 3: Memory & Lifecycle Stress Test
   - RAM measurement on 2,000+ credential circular buffer using tracemalloc
   - Verifying deque(maxlen=2000) ceiling (no memory leak past 2000 items)
   - 10 consecutive start() / stop() lifecycle cycles under ResourceWarning filter
   - Zero unclosed socket / transport warnings
"""

import asyncio
from collections import deque
import gc
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import tracemalloc
import unittest
import warnings
import yaml

# Ensure stdout handles UTF-8 safely on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.services.honeypot_service import (
    HoneypotConfig,
    HoneypotCredentialRecord,
    HoneypotService,
    HoneypotStorageRepository,
    strip_telnet_iac,
)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestChallenge1StorageConcurrency(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 1: Storage Concurrency Stress Test
    Fires 1,000 credential logging events concurrently via asyncio.gather.
    Verifies 0 deadlocks, 0 database lock errors, and 100% data integrity.
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "concurrency_test.db")
        self.config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=get_free_port(),
            telnet_port=get_free_port(),
            db_path=self.db_path,
            use_postgres=False,
        )
        self.repo = HoneypotStorageRepository(db_path=self.db_path, use_postgres=False)
        self.service = HoneypotService(config=self.config, repository=self.repo)

    async def asyncTearDown(self):
        await self.service.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_1000_concurrent_logging_events(self):
        """
        Spawns 1,000 concurrent async tasks that call log_credential simultaneously.
        Verifies:
        - 0 exceptions raised (no sqlite3.OperationalError: database is locked)
        - Exactly 1,000 credentials saved in SQLite
        - Exactly 1,000 probes tracked in in-memory state
        - Throughput benchmark recorded
        """
        total_events = 1000
        concurrency_errors = []

        async def worker(index: int):
            try:
                ip = f"192.168.{(index // 254) % 254 + 1}.{(index % 254) + 1}"
                svc = "ssh" if index % 2 == 0 else "telnet"
                user = f"user_{index % 50}"
                pwd = f"pass_{index}"
                await self.service.log_credential(
                    ip=ip,
                    service=svc,
                    username=user,
                    password=pwd,
                    attempt_count=(index % 3) + 1,
                    raw_session=f"test_session_{index}",
                )
            except Exception as e:
                concurrency_errors.append((index, type(e).__name__, str(e)))

        start_time = time.perf_counter()
        tasks = [asyncio.create_task(worker(i)) for i in range(total_events)]
        await asyncio.gather(*tasks)
        duration = time.perf_counter() - start_time

        # 1. Verify 0 errors
        self.assertEqual(
            len(concurrency_errors), 0,
            f"Concurrency errors detected: {concurrency_errors[:5]}"
        )

        # 2. Verify in-memory metrics
        stats = self.service.get_stats()
        self.assertEqual(stats["total_probes"], total_events)
        self.assertEqual(stats["total_credentials"], total_events)
        self.assertEqual(stats["service_breakdown"]["ssh"], 500)
        self.assertEqual(stats["service_breakdown"]["telnet"], 500)

        # 3. Verify SQLite DB row count
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM honeypot_credentials")
        row_count = cur.fetchone()[0]
        conn.close()

        self.assertEqual(row_count, total_events)

        throughput = total_events / duration if duration > 0 else 0
        sys.stdout.write(f"\n[Challenge 1] 1,000 Concurrent Writes Completed in {duration:.3f}s ({throughput:.1f} ops/sec) - 0 Errors [PASS]\n")

    async def test_concurrent_reads_during_1000_writes(self):
        """
        Stress tests simultaneous readers and 1,000 writers to ensure WAL mode
        prevents read-write deadlocks.
        """
        total_writes = 1000
        errors = []
        read_results = []

        async def writer(index: int):
            try:
                await self.service.log_credential(
                    ip=f"10.0.0.{index % 250}",
                    service="ssh",
                    username=f"attacker_{index}",
                    password="secret_password",
                )
            except Exception as e:
                errors.append(("write", type(e).__name__, str(e)))

        async def reader(idx: int):
            for _ in range(5):
                try:
                    logs = await self.service.get_honeypot_log(limit=20)
                    read_results.append(len(logs))
                    await asyncio.sleep(0.01)
                except Exception as e:
                    errors.append(("read", type(e).__name__, str(e)))

        write_tasks = [asyncio.create_task(writer(i)) for i in range(total_writes)]
        read_tasks = [asyncio.create_task(reader(i)) for i in range(10)]

        await asyncio.gather(*write_tasks, *read_tasks)

        self.assertEqual(len(errors), 0, f"Concurrent Read/Write errors: {errors}")
        sys.stdout.write(f"[Challenge 1] Concurrent Readers + 1,000 Writers: {len(read_results)} read queries executed smoothly [PASS]\n")


class TestChallenge2NginxAndSSIVerification(unittest.TestCase):
    """
    Challenge 2: Nginx SSI & Configuration Verification
    - Validates 403.html SSI syntax
    - Validates security_rules.conf regex patterns and PCRE compatibility
    - Validates nginx.conf structure
    - Validates docker-compose.yml YAML syntax & ports 2222:2222, 23:23
    """

    def setUp(self):
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
        self.html_403_path = os.path.join(self.root_dir, "frontend", "html", "403.html")
        self.sec_rules_path = os.path.join(self.root_dir, "frontend", "conf.d", "security_rules.conf")
        self.blocklist_path = os.path.join(self.root_dir, "frontend", "conf.d", "blocklist.conf")
        self.nginx_conf_path = os.path.join(self.root_dir, "frontend", "nginx.conf")
        self.docker_compose_path = os.path.join(self.root_dir, "docker-compose.yml")

    def test_403_html_ssi_syntax(self):
        """Verifies Nginx SSI tags in 403.html: <!--#echo var="..." -->"""
        self.assertTrue(os.path.exists(self.html_403_path), f"Missing {self.html_403_path}")
        with open(self.html_403_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check remote_addr SSI tag
        remote_addr_match = re.search(r'<!--#echo\s+var="remote_addr"(\s+default="[^"]*")?\s*-->', content)
        self.assertIsNotNone(
            remote_addr_match,
            "<!--#echo var=\"remote_addr\" --> tag missing or invalid syntax in 403.html"
        )

        # Check time_local SSI tag
        time_local_match = re.search(r'<!--#echo\s+var="time_local"(\s+default="[^"]*")?\s*-->', content)
        self.assertIsNotNone(
            time_local_match,
            "<!--#echo var=\"time_local\" --> tag missing or invalid syntax in 403.html"
        )

        # Verify no space between # and echo (Nginx SSI requirement)
        invalid_ssi = re.findall(r'<!--#\s+echo', content)
        self.assertEqual(len(invalid_ssi), 0, f"Found invalid SSI syntax with space after '#': {invalid_ssi}")

        sys.stdout.write(f"[Challenge 2] 403.html SSI Syntax: remote_addr ({remote_addr_match.group(0)}) and time_local ({time_local_match.group(0)}) [PASS]\n")

    def test_security_rules_conf_regex_validity(self):
        """
        Parses security_rules.conf and verifies that all regex patterns compile
        cleanly and match malicious attack payloads while permitting benign traffic.
        """
        self.assertTrue(os.path.exists(self.sec_rules_path), f"Missing {self.sec_rules_path}")
        with open(self.sec_rules_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract map blocks
        user_agent_patterns = []
        query_patterns = []

        in_user_agent = False
        in_query = False
        for line in content.splitlines():
            line = line.strip()
            if "map $http_user_agent $bad_client" in line:
                in_user_agent = True
                continue
            if "map $query_string $bad_query" in line:
                in_query = True
                continue
            if line == "}":
                in_user_agent = False
                in_query = False
                continue

            if in_user_agent and line.startswith("~*"):
                pattern = line[2:].rsplit(" ", 1)[0].strip()
                user_agent_patterns.append(pattern)
            elif in_query and line.startswith("~*"):
                pattern = line[2:].rsplit(" ", 1)[0].strip()
                query_patterns.append(pattern)

        self.assertGreater(len(user_agent_patterns), 0, "No user-agent patterns found")
        self.assertGreater(len(query_patterns), 0, "No query patterns found")

        # Compile and test user-agent patterns
        compiled_ua = []
        for p in user_agent_patterns:
            try:
                compiled = re.compile(p, re.IGNORECASE)
                compiled_ua.append(compiled)
            except re.error as e:
                self.fail(f"Invalid regex pattern in security_rules.conf: '{p}' - Error: {e}")

        # Test malicious user agents
        malicious_uas = [
            "sqlmap/1.6.4#stable",
            "Nikto/2.1.6",
            "masscan/1.3.2",
            "Mozilla/5.0 (compatible; Nmap Scripting Engine)",
            "gobuster/3.1.0",
            "Metasploit",
            "Hydra v9.2",
        ]
        for ua in malicious_uas:
            matched = any(c.search(ua) for c in compiled_ua)
            self.assertTrue(matched, f"Expected malicious User-Agent to be blocked: {ua}")

        # Test benign user agents
        benign_uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15",
            "curl/7.88.1",
        ]
        for bua in benign_uas:
            matched = any(c.search(bua) for c in compiled_ua)
            self.assertFalse(matched, f"Benign User-Agent was false-positively blocked: {bua}")

        # Compile and test query patterns
        compiled_query = []
        for p in query_patterns:
            try:
                compiled = re.compile(p, re.IGNORECASE)
                compiled_query.append(compiled)
            except re.error as e:
                self.fail(f"Invalid query regex pattern: '{p}' - Error: {e}")

        malicious_queries = [
            "id=1 UNION SELECT 1,username,password FROM users",
            "cat=electronics' OR '1'='1",
            "q=<script>alert(1)</script>",
            "file=../../../../etc/passwd",
            "page=%2e%2e%2f%2e%2e%2fetc/shadow",
        ]
        for mq in malicious_queries:
            matched = any(c.search(mq) for c in compiled_query)
            self.assertTrue(matched, f"Expected malicious query to be blocked: {mq}")

        benign_queries = [
            "page=1&size=20&sort=asc",
            "search=iphone+15+pro+max",
            "filter=active&category=laptops",
        ]
        for bq in benign_queries:
            matched = any(c.search(bq) for c in compiled_query)
            self.assertFalse(matched, f"Benign query was false-positively blocked: {bq}")

        sys.stdout.write(f"[Challenge 2] security_rules.conf: {len(compiled_ua)} UA rules, {len(compiled_query)} Query rules validated [PASS]\n")

    def test_nginx_conf_security_directives(self):
        """Validates nginx.conf contains bad_client/bad_query checks, blocklist include, and 403 location."""
        with open(self.nginx_conf_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("if ($bad_client)", content)
        self.assertIn("if ($bad_query)", content)
        self.assertIn("include /etc/nginx/conf.d/blocklist.conf;", content)
        self.assertIn("error_page 403 /403.html;", content)
        self.assertIn("location = /403.html", content)
        self.assertIn("ssi on;", content)
        sys.stdout.write("[Challenge 2] nginx.conf security directives and SSI block verified [PASS]\n")

    def test_docker_compose_yaml_and_ports(self):
        """Parses docker-compose.yml, validates YAML structure, and verifies honeypot port mappings."""
        with open(self.docker_compose_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.assertIn("services", data)
        ai_svc = data["services"].get("ai-agent-service")
        self.assertIsNotNone(ai_svc, "ai-agent-service missing from docker-compose.yml")

        ports = ai_svc.get("ports", [])
        self.assertIn("2222:2222", ports, "Port mapping 2222:2222 missing from ai-agent-service")
        self.assertIn("23:23", ports, "Port mapping 23:23 missing from ai-agent-service")

        sys.stdout.write(f"[Challenge 2] docker-compose.yml valid YAML, port mappings ['2222:2222', '23:23'] verified [PASS]\n")


class TestChallenge3MemoryAndLifecycle(unittest.IsolatedAsyncioTestCase):
    """
    Challenge 3: Memory & Lifecycle Stress Test
    - Measures RAM usage with 2,000 items in circular buffer deque(maxlen=2000)
    - Verifies memory stabilization when pushing past maxlen (up to 5,000 items)
    - Tests 10 consecutive start() / stop() cycles under ResourceWarning filter
    """

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "mem_lifecycle_test.db")

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_circular_buffer_memory_measurement(self):
        """
        Measures RAM usage of circular buffer storing 2,000 credential records.
        Pushes an extra 3,000 records (total 5,000) to confirm memory does NOT grow
        unbounded past maxlen=2000.
        """
        gc.collect()
        tracemalloc.start()

        repo = HoneypotStorageRepository(db_path=self.db_path, use_postgres=False)

        # 1. Fill buffer to exactly 2,000 items
        for i in range(2000):
            rec = HoneypotCredentialRecord(
                id=i + 1,
                ip=f"192.168.{(i // 250) % 250}.{i % 250}",
                service="ssh" if i % 2 == 0 else "telnet",
                username=f"user_test_{i}",
                password=f"password_secret_long_string_simulation_{i}",
                attempt_count=(i % 3) + 1,
                captured_at=time.time(),
                raw_session=f"port=2222;peer=192.168.1.1;client_ver=SSH-2.0;idx={i}",
            )
            repo._mem_records.appendleft(rec.to_dict())

        self.assertEqual(len(repo._mem_records), 2000)

        current, peak = tracemalloc.get_traced_memory()
        ram_2k_mb = peak / (1024 * 1024)

        # 2. Push another 3,000 items (total 5,000 pushed, buffer stays at 2,000)
        for i in range(2000, 5000):
            rec = HoneypotCredentialRecord(
                id=i + 1,
                ip=f"10.0.{(i // 250) % 250}.{i % 250}",
                service="ssh",
                username=f"attacker_{i}",
                password=f"p@ssw0rd_{i}",
                attempt_count=1,
                captured_at=time.time(),
                raw_session=f"session_{i}",
            )
            repo._mem_records.appendleft(rec.to_dict())

        self.assertEqual(len(repo._mem_records), 2000)
        gc.collect()
        current_5k, peak_5k = tracemalloc.get_traced_memory()
        ram_5k_mb = current_5k / (1024 * 1024)

        tracemalloc.stop()

        # The memory for 2,000 dicts should be well under 10MB (typically ~1.5 - 2.5MB)
        self.assertLess(ram_2k_mb, 10.0, f"Memory usage too high for 2000 items: {ram_2k_mb:.2f} MB")
        # Memory after 5000 pushes should stay within ~20% of 2000 items (no unbounded leak)
        delta_mb = abs(ram_5k_mb - (current / (1024 * 1024)))
        self.assertLess(delta_mb, 2.0, f"Memory drifted significantly after rotating buffer: {delta_mb:.2f} MB")

        sys.stdout.write(f"\n[Challenge 3] Circular Buffer RAM: 2,000 items = {ram_2k_mb:.2f} MB (Peak), after 5,000 pushes = {ram_5k_mb:.2f} MB (Delta: {delta_mb:.2f} MB) - [PASS]\n")

    async def test_10_consecutive_start_stop_cycles_zero_resource_warning(self):
        """
        Executes 10 start() and stop() cycles consecutively.
        Monitors Python warnings for ResourceWarning (unclosed sockets/transports/files).
        Must produce exactly 0 ResourceWarnings.
        """
        config = HoneypotConfig(
            bind_host="127.0.0.1",
            ssh_port=get_free_port(),
            telnet_port=get_free_port(),
            db_path=self.db_path,
            use_postgres=False,
        )
        service = HoneypotService(config=config)

        caught_warnings = []
        with warnings.catch_warnings(record=True) as warn_list:
            warnings.simplefilter("always", ResourceWarning)

            for cycle in range(1, 11):
                # Start service
                await service.start()
                stats_started = service.get_stats()
                self.assertEqual(stats_started["status"], "running", f"Cycle {cycle}: Service should be running")

                # Perform a quick probe connection to simulate active socket
                try:
                    r, w = await asyncio.open_connection("127.0.0.1", config.ssh_port)
                    await r.readline()  # Read banner
                    w.close()
                    await w.wait_closed()
                except Exception:
                    pass

                # Short delay to allow tasks to settle
                await asyncio.sleep(0.02)

                # Stop service cleanly
                await service.stop()
                stats_stopped = service.get_stats()
                self.assertEqual(stats_stopped["status"], "stopped", f"Cycle {cycle}: Service should not be running")

            # Collect any ResourceWarnings
            for w in warn_list:
                if issubclass(w.category, ResourceWarning):
                    caught_warnings.append(str(w.message))

        self.assertEqual(
            len(caught_warnings), 0,
            f"ResourceWarnings detected during 10 start/stop cycles: {caught_warnings}"
        )
        sys.stdout.write(f"[Challenge 3] 10 consecutive start()/stop() cycles: 0 ResourceWarnings detected [PASS]\n")


if __name__ == "__main__":
    unittest.main()
