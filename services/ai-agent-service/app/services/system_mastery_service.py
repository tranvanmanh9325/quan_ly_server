"""
system_mastery_service.py — Unrestricted Root System Mastery Engine.

Empowers AI Agent Tieu Bao Bao with comprehensive host-level systems administration:
- Unrestricted command execution lifting artificial barriers while guarding spinal hardware safety.
- Staging and execution of arbitrary Bash/Python system scripts via secure Base64 staging with automatic cleanup.
- Full Docker container lifecycle administration (list, inspect, logs, start, stop, restart, prune).
- 6-step holistic system resource optimization (RAM drop_caches, docker prune, journal vacuum, temp cleanup, malloc_trim).
"""

from __future__ import annotations

import asyncio
import base64
import ctypes
import gc
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)

# Production-critical containers that require explicit force confirmation before stopping
CRITICAL_CONTAINERS = {
    "dashboard_db",
    "postgres",
    "dashboard_ai_agent",
    "dashboard_frontend",
    "nginx",
}


def _parse_memory_mb(free_output: str) -> Dict[str, int]:
    """Parses output from `free -m` into structured values."""
    mem_info = {"total": 0, "used": 0, "free": 0, "available": 0}
    try:
        lines = free_output.strip().splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if line.lower().startswith("mem"):
                parts = line.split()
                if len(parts) >= 7:
                    mem_info["total"] = int(parts[1])
                    mem_info["used"] = int(parts[2])
                    mem_info["free"] = int(parts[3])
                    mem_info["available"] = int(parts[6])
                elif len(parts) >= 4:
                    mem_info["total"] = int(parts[1])
                    mem_info["used"] = int(parts[2])
                    mem_info["free"] = int(parts[3])
                    mem_info["available"] = int(parts[3])
                break
    except Exception as exc:
        logger.warning("[SystemMastery] Failed to parse free -m output: %s", exc)
    return mem_info


def _parse_disk_mb(df_output: str) -> Dict[str, int]:
    """Parses output from `df -m /` into structured values."""
    disk_info = {"total": 0, "used": 0, "available": 0}
    try:
        lines = [l.strip() for l in df_output.strip().splitlines() if l.strip()]
        for line in lines[1:]:  # Skip header
            parts = line.split()
            if len(parts) >= 4:
                disk_info["total"] = int(parts[1])
                disk_info["used"] = int(parts[2])
                disk_info["available"] = int(parts[3])
                break
    except Exception as exc:
        logger.warning("[SystemMastery] Failed to parse df -m output: %s", exc)
    return disk_info


class SystemMasteryService:
    """
    Core service for unrestricted root and host system administration.
    """

    def __init__(self, ssh_client: Optional[Any] = None):
        self._ssh_client = ssh_client

    @property
    def ssh_client(self) -> Any:
        if self._ssh_client is None:
            from app.core.ssh_client import SshClient
            self._ssh_client = SshClient()
        return self._ssh_client

    async def run_command_unrestricted(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        """
        Executes an unrestricted command on the host via SSH, supporting root/sudo,
        package management (apt, pip), systemctl, docker, and shell pipelines without
        artificial barriers, while preserving core hardware safety veto.
        """
        if not command or not command.strip():
            return {
                "status": "error",
                "command": "",
                "output": "",
                "message": "Lệnh không được để trống.",
            }

        cmd_clean = command.strip()
        start_time = time.time()

        try:
            output = await self.ssh_client.execute_command(
                cmd_clean,
                timeout=timeout,
                unrestricted=True,
            )

            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            is_blocked = output.startswith("BLOCKED:")

            return {
                "status": "blocked" if is_blocked else "success",
                "command": cmd_clean,
                "output": output,
                "execution_time_ms": elapsed_ms,
                "message": "Lệnh bị chặn bởi cơ chế bảo vệ phần cứng." if is_blocked else f"Thực thi thành công trong {elapsed_ms}ms.",
            }
        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            logger.error("[SystemMastery] Execution failed for '%s': %s", cmd_clean, exc)
            return {
                "status": "error",
                "command": cmd_clean,
                "output": str(exc),
                "execution_time_ms": elapsed_ms,
                "message": f"Lỗi khi thực thi lệnh trên host: {str(exc)}",
            }

    async def execute_system_script(
        self,
        script_code: str,
        interpreter: str = "bash",
        timeout: int = 120,
        run_as_root: bool = False,
    ) -> Dict[str, Any]:
        """
        Stages and executes a complete multi-line Bash or Python script on the host:
        1. Encodes script into Base64 to prevent special character corruption over SSH.
        2. Stages script to /tmp/agent_script_{ts}_{uuid}.{ext} and applies chmod 700.
        3. Executes script with the specified interpreter and gathers exit_code + stdout.
        4. Guarantees temporary script file removal in finally block (Zero-Leak Staging).
        """
        if not script_code or not script_code.strip():
            return {
                "status": "error",
                "message": "Mã nguồn script không được để trống.",
            }

        valid_interpreters = {"bash", "sh", "python3"}
        interp = interpreter.lower().strip()
        if interp not in valid_interpreters:
            interp = "bash"

        ext = "py" if interp == "python3" else "sh"
        unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        script_path = f"/tmp/agent_script_{unique_id}.{ext}"

        # Base64 encode script payload
        b64_payload = base64.b64encode(script_code.encode("utf-8")).decode("ascii")

        stage_cmd = f"echo '{b64_payload}' | base64 -d > {script_path} && chmod 700 {script_path}"
        start_time = time.time()

        try:
            # Step 1: Stage script to host
            stage_res = await self.ssh_client.execute_command(stage_cmd, timeout=30, unrestricted=True)
            if "BLOCKED:" in stage_res:
                return {
                    "status": "blocked",
                    "script_path": script_path,
                    "output": stage_res,
                    "message": "Staging script bị chặn vì lý do bảo mật.",
                }

            # Step 2: Execute script and capture exit code
            exec_prefix = "sudo -n " if run_as_root else ""
            run_cmd = f"{exec_prefix}{interp} {script_path}; __RET__=$?; echo '__SCRIPT_EXIT_CODE__:'$__RET__"

            raw_output = await self.ssh_client.execute_command(run_cmd, timeout=timeout, unrestricted=True)

            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            # Step 3: Parse exit code
            exit_code = 0
            clean_output = raw_output
            code_match = re.search(r"__SCRIPT_EXIT_CODE__:(\d+)", raw_output)
            if code_match:
                exit_code = int(code_match.group(1))
                clean_output = re.sub(r"__SCRIPT_EXIT_CODE__:\d+", "", raw_output).strip()

            is_success = (exit_code == 0) and not clean_output.startswith("BLOCKED:")

            return {
                "status": "success" if is_success else "error",
                "interpreter": interp,
                "script_path": script_path,
                "exit_code": exit_code,
                "run_as_root": run_as_root,
                "output": clean_output,
                "execution_time_ms": elapsed_ms,
                "message": (
                    f"Thực thi script {interp} thành công (exit code {exit_code})."
                    if is_success
                    else f"Script {interp} kết thúc với lỗi (exit code {exit_code})."
                ),
            }

        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            logger.error("[SystemMastery] Script execution error: %s", exc)
            return {
                "status": "error",
                "interpreter": interp,
                "script_path": script_path,
                "exit_code": -1,
                "output": str(exc),
                "execution_time_ms": elapsed_ms,
                "message": f"Lỗi khi thực thi script: {str(exc)}",
            }

        finally:
            # Zero-Leak Staging Cleanup: Ensure temporary script file is removed on host
            try:
                cleanup_cmd = f"rm -f {script_path}"
                await self.ssh_client.execute_command(cleanup_cmd, timeout=10, unrestricted=True)
                logger.info("[SystemMastery] Cleaned up temporary host script: %s", script_path)
            except Exception as clean_err:
                logger.warning("[SystemMastery] Failed to clean temporary host script %s: %s", script_path, clean_err)

    async def manage_docker_containers(
        self,
        action: str,
        container_name: Optional[str] = None,
        force: bool = False,
        lines: int = 100,
    ) -> Dict[str, Any]:
        """
        Manages Docker container lifecycle on the host via SSH:
        Supported actions: 'list', 'inspect', 'logs', 'start', 'stop', 'restart', 'prune'.
        Guards production-critical containers against accidental termination.
        """
        act = action.lower().strip()
        cname = (container_name or "").strip()

        # Input validation
        requires_container = {"inspect", "logs", "start", "stop", "restart"}
        if act in requires_container and not cname:
            return {
                "status": "error",
                "action": act,
                "message": f"Hành động '{act}' yêu cầu cung cấp tham số 'container_name'.",
            }

        # Production safety guard for critical containers
        if act == "stop" and cname in CRITICAL_CONTAINERS and not force:
            return {
                "status": "blocked",
                "action": act,
                "container_name": cname,
                "message": (
                    f"Container '{cname}' là dịch vụ Production trọng yếu đang phục vụ người dùng. "
                    f"Thao tác dừng bị từ chối. Vui lòng cung cấp force=True nếu bạn thực sự muốn dừng."
                ),
            }

        start_time = time.time()

        # Build host docker command
        if act == "list":
            cmd = "docker ps -a --format '{{json .}}'"
        elif act == "inspect":
            cmd = f"docker inspect {cname}"
        elif act == "logs":
            tail_lines = max(10, min(lines, 1000))
            cmd = f"docker logs --tail {tail_lines} --timestamps {cname}"
        elif act == "start":
            cmd = f"docker start {cname}"
        elif act == "stop":
            cmd = f"docker stop -t 0 {cname}" if force else f"docker stop {cname}"
        elif act == "restart":
            cmd = f"docker restart {cname}"
        elif act == "prune":
            cmd = "docker container prune -f && docker image prune -f"
        else:
            return {
                "status": "error",
                "action": act,
                "message": f"Hành động không hợp lệ: '{act}'. Các hành động hỗ trợ: list, inspect, logs, start, stop, restart, prune.",
            }

        try:
            raw_output = await self.ssh_client.execute_command(cmd, timeout=60, unrestricted=True)
            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            parsed_data: Any = None
            if act == "list":
                parsed_data = []
                for line in raw_output.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            parsed_data.append(json.loads(line))
                        except Exception:
                            pass
            elif act == "inspect":
                try:
                    parsed_data = json.loads(raw_output)
                except Exception:
                    parsed_data = raw_output
            else:
                parsed_data = raw_output

            is_error = raw_output.startswith("Error:") or raw_output.startswith("BLOCKED:")

            return {
                "status": "error" if is_error else "success",
                "action": act,
                "container_name": cname if cname else None,
                "data": parsed_data,
                "raw_output": raw_output,
                "execution_time_ms": elapsed_ms,
                "message": f"Thực hiện '{act}' trên Docker thành công trong {elapsed_ms}ms.",
            }

        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            logger.error("[SystemMastery] Docker action '%s' failed: %s", act, exc)
            return {
                "status": "error",
                "action": act,
                "container_name": cname if cname else None,
                "output": str(exc),
                "execution_time_ms": elapsed_ms,
                "message": f"Lỗi khi thực hiện hành động Docker '{act}': {str(exc)}",
            }

    async def optimize_system_resources(self) -> Dict[str, Any]:
        """
        Executes a 6-step comprehensive resource optimization procedure on the host and container:
        1. Pre-optimization snapshot: reads RAM and Disk metrics (free -m, df -m /).
        2. Kernel cache flush: executes sync && drop_caches.
        3. Docker garbage collection: prunes unused containers and dangling images (--volumes=false).
        4. Systemd journal vacuum: cleans journal logs older than 2 days or > 100MB.
        5. Temporary files sweep: deletes expired files in /tmp download directories.
        6. In-container memory trim: invokes gc.collect() and glibc malloc_trim(0).
        7. Post-optimization snapshot: calculates freed RAM and Disk space.
        """
        start_time = time.time()
        steps_executed: List[str] = []

        try:
            # Step 1: Pre-optimization snapshot
            pre_free = await self.ssh_client.execute_command("free -m", timeout=15, unrestricted=True)
            pre_df = await self.ssh_client.execute_command("df -m /", timeout=15, unrestricted=True)
            mem_before = _parse_memory_mb(pre_free)
            disk_before = _parse_disk_mb(pre_df)
            steps_executed.append("1. Ghi nhận snapshot tài nguyên ban đầu (RAM & Disk)")

            # Step 2: Kernel Cache Flushing
            drop_cmd = "sync && echo 3 | sudo -n tee /proc/sys/vm/drop_caches"
            await self.ssh_client.execute_command(drop_cmd, timeout=30, unrestricted=True)
            steps_executed.append("2. Xả bộ nhớ đệm Kernel Linux (sync && drop_caches)")

            # Step 3: Docker Garbage Collection
            prune_cmd = "docker system prune -f --volumes=false"
            await self.ssh_client.execute_command(prune_cmd, timeout=60, unrestricted=True)
            steps_executed.append("3. Dọn rác Docker containers và images (bảo toàn volume dữ liệu)")

            # Step 4: Systemd Journal Vacuuming
            journal_cmd = "sudo -n journalctl --vacuum-time=2d --vacuum-size=100M"
            await self.ssh_client.execute_command(journal_cmd, timeout=30, unrestricted=True)
            steps_executed.append("4. Thu dọn Systemd Journal log quá 2 ngày hoặc >100MB")

            # Step 5: Temporary Files Sweep on Host
            temp_cleanup_cmd = (
                "find /tmp/media_downloads/ /tmp/direct_downloads/ /tmp/downloads/ "
                "-type f -mmin +720 -delete 2>/dev/null || true"
            )
            await self.ssh_client.execute_command(temp_cleanup_cmd, timeout=30, unrestricted=True)
            steps_executed.append("5. Dọn dẹp tệp tạm cũ trên máy chủ (/tmp download caches)")

            # Step 6: In-Container Memory Trim
            try:
                gc.collect()
                if hasattr(ctypes, "CDLL") and os.name != "nt":
                    try:
                        libc = ctypes.CDLL("libc.so.6")
                        if hasattr(libc, "malloc_trim"):
                            libc.malloc_trim(0)
                    except Exception:
                        pass
                steps_executed.append("6. Thu hồi RAM nội bộ container (gc.collect & malloc_trim)")
            except Exception as gc_err:
                logger.debug("[SystemMastery] Container memory trim note: %s", gc_err)

            # Step 7: Post-optimization snapshot
            post_free = await self.ssh_client.execute_command("free -m", timeout=15, unrestricted=True)
            post_df = await self.ssh_client.execute_command("df -m /", timeout=15, unrestricted=True)
            mem_after = _parse_memory_mb(post_free)
            disk_after = _parse_disk_mb(post_df)

            ram_freed = max(0, mem_after["available"] - mem_before["available"])
            disk_freed = max(0, disk_before["used"] - disk_after["used"])
            elapsed_sec = round(time.time() - start_time, 2)

            return {
                "status": "success",
                "before": {
                    "ram_available_mb": mem_before["available"],
                    "ram_used_mb": mem_before["used"],
                    "disk_used_mb": disk_before["used"],
                    "disk_available_mb": disk_before["available"],
                },
                "after": {
                    "ram_available_mb": mem_after["available"],
                    "ram_used_mb": mem_after["used"],
                    "disk_used_mb": disk_after["used"],
                    "disk_available_mb": disk_after["available"],
                },
                "freed": {
                    "ram_freed_mb": ram_freed,
                    "disk_freed_mb": disk_freed,
                },
                "steps_executed": steps_executed,
                "execution_time_sec": elapsed_sec,
                "message": (
                    f"Tối ưu hóa tài nguyên thành công trong {elapsed_sec}s. "
                    f"Đã giải phóng ~{ram_freed} MB RAM khả dụng và ~{disk_freed} MB đĩa."
                ),
            }

        except Exception as exc:
            elapsed_sec = round(time.time() - start_time, 2)
            logger.error("[SystemMastery] Resource optimization error: %s", exc)
            return {
                "status": "error",
                "steps_executed": steps_executed,
                "output": str(exc),
                "execution_time_sec": elapsed_sec,
                "message": f"Lỗi trong quá trình tối ưu hóa tài nguyên: {str(exc)}",
            }


# Module-level singleton instance
system_mastery_service = SystemMasteryService()


async def run_command_unrestricted(command: str, timeout: int = 60) -> Dict[str, Any]:
    """
    Public module-level contract for unrestricted shell command execution.
    """
    return await system_mastery_service.run_command_unrestricted(command, timeout=timeout)


async def execute_system_script(
    script_code: str,
    interpreter: str = "bash",
    timeout: int = 120,
    run_as_root: bool = False,
) -> Dict[str, Any]:
    """
    Public module-level contract for system script execution.
    """
    return await system_mastery_service.execute_system_script(
        script_code,
        interpreter=interpreter,
        timeout=timeout,
        run_as_root=run_as_root,
    )


async def manage_docker_containers(
    action: str,
    container_name: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Public module-level contract for Docker container administration.
    """
    return await system_mastery_service.manage_docker_containers(
        action=action,
        container_name=container_name,
        force=force,
    )


async def optimize_system_resources() -> Dict[str, Any]:
    """
    Public module-level contract for holistic system resources optimization.
    """
    return await system_mastery_service.optimize_system_resources()
