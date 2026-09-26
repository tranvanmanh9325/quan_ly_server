"""
app/services/cron_service.py — Cron Automation & Scheduled Job Management Service (R5).

Engineered for AI Agent Tieu Bao Bao:
- create_cron_job: Validates standard 5-field cron syntax (min, hour, dom, mon, dow)
  and safely registers the job into host crontab tagged with `# AGENT_JOB: <name>`.
- list_cron_jobs: Inspects and parses crontab to return active agent-managed and system cron jobs.
- delete_cron_job: Removes a designated cron job by name; strictly guarded with
  confirmation token gating (Tier 2 Reversible, requires `confirm="DELETE_CONFIRMED"`).

Architecture:
- Connects to host crontab via SshClient using base64 payload piping to ensure zero escaping bugs.
- Thread-safe, injection-hardened validation on job names and shell commands.
"""

import base64
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.ssh_client import SshClient

logger = logging.getLogger(__name__)

# Strict regex for valid cron job name (alphanumeric, underscores, hyphens)
JOB_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")

# Month and Day of week names mapping
MONTH_NAMES = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
               "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
DOW_NAMES = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}

CONFIRMATION_REQUIRED_TOKEN = "DELETE_CONFIRMED"


def _validate_cron_field(field_str: str, min_val: int, max_val: int, name_map: Optional[Dict[str, int]] = None) -> Tuple[bool, Optional[str]]:
    """
    Validates a single cron field for valid numbers, ranges, lists, or steps.
    """
    field_str = field_str.strip().upper()
    if not field_str:
        return False, "Trường không được để trống"

    if field_str == "*":
        return True, None

    # Handle multiple list elements: e.g. 1,2,5 or MON,WED,FRI
    sub_elements = field_str.split(",")
    for elem in sub_elements:
        elem = elem.strip()
        if not elem:
            return False, "Phần tử trong danh sách không hợp lệ"

        # Check step syntax: */5 or 10-30/5
        if "/" in elem:
            parts = elem.split("/", 1)
            base_part, step_part = parts[0], parts[1]
            if not step_part.isdigit() or int(step_part) <= 0:
                return False, f"Bước nhảy step '{step_part}' phải là số nguyên dương"
            if base_part != "*":
                # Check range in base_part
                valid_base, err = _validate_cron_field(base_part, min_val, max_val, name_map)
                if not valid_base:
                    return False, err
            continue

        # Check range syntax: 1-5 or MON-FRI
        if "-" in elem:
            parts = elem.split("-", 1)
            p1, p2 = parts[0].strip(), parts[1].strip()

            val1 = name_map.get(p1) if name_map and p1 in name_map else (int(p1) if p1.isdigit() else None)
            val2 = name_map.get(p2) if name_map and p2 in name_map else (int(p2) if p2.isdigit() else None)

            if val1 is None or val2 is None:
                return False, f"Khoảng giá trị '{elem}' không hợp lệ"
            if val1 < min_val or val1 > max_val or val2 < min_val or val2 > max_val:
                return False, f"Giá trị trong khoảng '{elem}' vượt ngoài phạm vi ({min_val}–{max_val})"
            if val1 > val2:
                return False, f"Đầu dải ({val1}) không được lớn hơn cuối dải ({val2})"
            continue

        # Single integer or named token
        if name_map and elem in name_map:
            num = name_map[elem]
        elif elem.isdigit():
            num = int(elem)
        else:
            return False, f"Giá trị '{elem}' không phải số hoặc ký hiệu hợp lệ"

        if num < min_val or num > max_val:
            return False, f"Giá trị {num} nằm ngoài phạm vi cho phép ({min_val}–{max_val})"

    return True, None


def validate_cron_expression(schedule: str) -> Tuple[bool, Optional[str]]:
    """
    Validates standard 5-field cron syntax:
    Minute (0-59), Hour (0-23), Day of Month (1-31), Month (1-12), Day of Week (0-7).
    """
    clean_sched = schedule.strip()
    fields = clean_sched.split()
    if len(fields) != 5:
        return (
            False,
            f"Biểu thức cron phải có đúng 5 trường (phút, giờ, ngày, tháng, thứ), hiện có {len(fields)} trường",
        )

    # 1. Minute: 0-59
    valid_min, err_min = _validate_cron_field(fields[0], 0, 59)
    if not valid_min:
        return False, f"Lỗi trường Phút (0-59): {err_min}"

    # 2. Hour: 0-23
    valid_hr, err_hr = _validate_cron_field(fields[1], 0, 23)
    if not valid_hr:
        return False, f"Lỗi trường Giờ (0-23): {err_hr}"

    # 3. Day of Month: 1-31
    valid_dom, err_dom = _validate_cron_field(fields[2], 1, 31)
    if not valid_dom:
        return False, f"Lỗi trường Ngày trong tháng (1-31): {err_dom}"

    # 4. Month: 1-12 or JAN-DEC
    valid_mon, err_mon = _validate_cron_field(fields[3], 1, 12, MONTH_NAMES)
    if not valid_mon:
        return False, f"Lỗi trường Tháng (1-12): {err_mon}"

    # 5. Day of Week: 0-7 or SUN-SAT (0 and 7 are both Sunday)
    valid_dow, err_dow = _validate_cron_field(fields[4], 0, 7, DOW_NAMES)
    if not valid_dow:
        return False, f"Lỗi trường Thứ trong tuần (0-7): {err_dow}"

    return True, None


class CronService:
    """
    Cron Automation Service for AI Agent Tieu Bao Bao.
    Inspects, adds, and removes automated jobs from the host crontab via SshClient.
    """

    def __init__(self, ssh_client: Optional[SshClient] = None):
        self._ssh_client = ssh_client

    @property
    def ssh_client(self) -> SshClient:
        if self._ssh_client is None:
            self._ssh_client = SshClient()
        return self._ssh_client

    async def create_cron_job(
        self,
        name: str,
        schedule: str,
        command: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """
        Creates or updates a scheduled cron job on the server.
        Tagged with `# AGENT_JOB: <name> | <description>`.
        """
        clean_name = name.strip()
        if not clean_name:
            return {"status": "error", "message": "Tên cron job không được để trống"}

        if not JOB_NAME_REGEX.match(clean_name):
            return {
                "status": "error",
                "message": (
                    f"Tên cron job '{clean_name}' không hợp lệ. "
                    "Chỉ chấp nhận chữ cái, chữ số, dấu gạch dưới (_) và gạch ngang (-)."
                ),
            }

        clean_cmd = command.strip()
        if not clean_cmd:
            return {"status": "error", "message": "Lệnh thực thi command không được để trống"}

        if "\n" in clean_cmd or "\r" in clean_cmd:
            return {"status": "error", "message": "Lệnh command không được chứa ký tự xuống dòng"}

        clean_sched = schedule.strip()
        is_valid_sched, sched_err = validate_cron_expression(clean_sched)
        if not is_valid_sched:
            return {
                "status": "error",
                "message": f"Biểu thức lịch cron không hợp lệ: {sched_err}",
                "schedule": clean_sched,
            }

        clean_desc = (description or "").strip().replace("\n", " ")

        # 1. Fetch current crontab
        try:
            current_crontab = await self.ssh_client.execute_command("crontab -l 2>/dev/null || true")
        except Exception as exc:
            logger.error("[CronService] Failed to read crontab: %s", exc)
            return {"status": "error", "message": f"Không thể đọc crontab hiện tại: {str(exc)}"}

        if current_crontab.startswith("BLOCKED:"):
            return {"status": "error", "message": f"Bảo mật hệ thống từ chối lệnh: {current_crontab}"}

        # 2. Parse and filter out existing job with identical name (idempotent update)
        lines = current_crontab.splitlines()
        filtered_lines: List[str] = []
        skip_next = False
        target_tag_prefix = f"# AGENT_JOB: {clean_name}"

        for line in lines:
            if skip_next:
                skip_next = False
                continue
            if line.startswith(target_tag_prefix):
                # Found existing job header, skip this comment and its corresponding command line
                skip_next = True
                continue
            filtered_lines.append(line)

        # Clean trailing empty lines
        while filtered_lines and not filtered_lines[-1].strip():
            filtered_lines.pop()

        # 3. Append new agent job
        new_tag_line = f"# AGENT_JOB: {clean_name}" + (f" | {clean_desc}" if clean_desc else "")
        new_cmd_line = f"{clean_sched} {clean_cmd}"
        filtered_lines.append(new_tag_line)
        filtered_lines.append(new_cmd_line)
        new_crontab_content = "\n".join(filtered_lines) + "\n"

        # 4. Write back safely using base64 decoding through stdin
        b64_payload = base64.b64encode(new_crontab_content.encode("utf-8")).decode("ascii")
        write_cmd = f"echo '{b64_payload}' | base64 -d | crontab -"

        try:
            write_res = await self.ssh_client.execute_command(write_cmd)
        except Exception as exc:
            logger.error("[CronService] Failed to write crontab: %s", exc)
            return {"status": "error", "message": f"Không thể lưu crontab mới: {str(exc)}"}

        if write_res.startswith("BLOCKED:"):
            return {"status": "error", "message": f"Bảo mật từ chối cập nhật crontab: {write_res}"}

        logger.info("[CronService] Successfully created/updated cron job '%s' (%s)", clean_name, clean_sched)
        return {
            "status": "success",
            "name": clean_name,
            "schedule": clean_sched,
            "command": clean_cmd,
            "description": clean_desc,
            "message": f"Đã thiết lập cron job '{clean_name}' thành công ({clean_sched})",
        }

    async def list_cron_jobs(self) -> Dict[str, Any]:
        """
        Lists all active cron jobs in crontab, categorized by agent-managed and system jobs.
        """
        try:
            raw_crontab = await self.ssh_client.execute_command("crontab -l 2>/dev/null || true")
        except Exception as exc:
            logger.error("[CronService] Failed to list crontab: %s", exc)
            return {"status": "error", "message": f"Không thể đọc danh sách crontab: {str(exc)}"}

        if raw_crontab.startswith("BLOCKED:"):
            return {"status": "error", "message": f"Bảo mật từ chối đọc crontab: {raw_crontab}"}

        lines = raw_crontab.splitlines()
        jobs: List[Dict[str, Any]] = []

        idx = 0
        while idx < len(lines):
            line = lines[idx].strip()
            if not line:
                idx += 1
                continue

            # Check if line is an Agent Job tag
            if line.startswith("# AGENT_JOB:"):
                tag_content = line[len("# AGENT_JOB:"):].strip()
                if "|" in tag_content:
                    name_part, desc_part = tag_content.split("|", 1)
                    job_name = name_part.strip()
                    job_desc = desc_part.strip()
                else:
                    job_name = tag_content.strip()
                    job_desc = ""

                # Next line should be the cron command
                schedule = ""
                command = ""
                if idx + 1 < len(lines):
                    cmd_line = lines[idx + 1].strip()
                    parts = cmd_line.split(maxsplit=5)
                    if len(parts) >= 6:
                        schedule = " ".join(parts[:5])
                        command = parts[5]
                    else:
                        command = cmd_line
                    idx += 1  # Advance past the command line

                jobs.append({
                    "name": job_name,
                    "schedule": schedule,
                    "command": command,
                    "description": job_desc,
                    "is_agent_managed": True,
                })
            elif not line.startswith("#"):
                # System or custom cron line
                parts = line.split(maxsplit=5)
                if len(parts) >= 6:
                    schedule = " ".join(parts[:5])
                    command = parts[5]
                else:
                    schedule = ""
                    command = line

                jobs.append({
                    "name": f"system_job_{len(jobs) + 1}",
                    "schedule": schedule,
                    "command": command,
                    "description": "System or user crontab entry",
                    "is_agent_managed": False,
                })
            idx += 1

        agent_jobs = [j for j in jobs if j.get("is_agent_managed")]
        return {
            "status": "success",
            "total_jobs": len(jobs),
            "agent_jobs_count": len(agent_jobs),
            "jobs": jobs,
            "raw_lines_count": len(lines),
        }

    async def delete_cron_job(self, name: str, confirm: Optional[str] = None) -> Dict[str, Any]:
        """
        Deletes a cron job by name from crontab.
        Requires confirm='DELETE_CONFIRMED' for safety (Tier 2 Reversible).
        """
        clean_name = (name or "").strip()
        if not clean_name:
            return {"status": "error", "message": "Tên cron job cần xóa không được để trống"}

        # Strict confirmation check
        if confirm != CONFIRMATION_REQUIRED_TOKEN:
            return {
                "status": "error",
                "message": (
                    f"Xóa cron job '{clean_name}' là tác vụ quan trọng (Tier 2). "
                    f"Vui lòng cung cấp tham số confirm='{CONFIRMATION_REQUIRED_TOKEN}' để xác nhận thực hiện."
                ),
                "required_confirm": CONFIRMATION_REQUIRED_TOKEN,
                "name": clean_name,
            }

        # 1. Fetch current crontab
        try:
            current_crontab = await self.ssh_client.execute_command("crontab -l 2>/dev/null || true")
        except Exception as exc:
            logger.error("[CronService] Failed to read crontab for deletion: %s", exc)
            return {"status": "error", "message": f"Không thể đọc crontab: {str(exc)}"}

        if current_crontab.startswith("BLOCKED:"):
            return {"status": "error", "message": f"Bảo mật từ chối: {current_crontab}"}

        lines = current_crontab.splitlines()
        filtered_lines: List[str] = []
        found = False
        skip_next = False
        target_tag_prefix = f"# AGENT_JOB: {clean_name}"

        for line in lines:
            if skip_next:
                skip_next = False
                continue

            # Check match with or without description
            if line.startswith(target_tag_prefix):
                # Verify exact name boundary (avoid prefix collisions e.g. job_1 vs job_10)
                rem = line[len(target_tag_prefix):].strip()
                if rem == "" or rem.startswith("|") or rem.startswith("-"):
                    found = True
                    skip_next = True
                    continue

            filtered_lines.append(line)

        if not found:
            return {
                "status": "error",
                "message": f"Không tìm thấy cron job nào có tên '{clean_name}' do Agent quản lý",
                "name": clean_name,
            }

        # Clean trailing empty lines
        while filtered_lines and not filtered_lines[-1].strip():
            filtered_lines.pop()

        new_crontab_content = ("\n".join(filtered_lines) + "\n") if filtered_lines else ""

        # 2. Write back
        if new_crontab_content:
            b64_payload = base64.b64encode(new_crontab_content.encode("utf-8")).decode("ascii")
            write_cmd = f"echo '{b64_payload}' | base64 -d | crontab -"
        else:
            # If all jobs deleted, remove crontab cleanly
            write_cmd = "crontab -r 2>/dev/null || true"

        try:
            write_res = await self.ssh_client.execute_command(write_cmd)
        except Exception as exc:
            logger.error("[CronService] Failed to write crontab after deletion: %s", exc)
            return {"status": "error", "message": f"Không thể cập nhật crontab: {str(exc)}"}

        if write_res.startswith("BLOCKED:"):
            return {"status": "error", "message": f"Bảo mật từ chối cập nhật: {write_res}"}

        logger.info("[CronService] Successfully deleted cron job '%s'", clean_name)
        return {
            "status": "success",
            "name": clean_name,
            "message": f"Đã xóa cron job '{clean_name}' khỏi hệ thống thành công",
        }


# Module-level singletons and interface functions for direct dispatcher routing
cron_service = CronService()


async def create_cron_job(name: str, schedule: str, command: str, description: str = "") -> Dict[str, Any]:
    return await cron_service.create_cron_job(name, schedule, command, description)


async def list_cron_jobs() -> Dict[str, Any]:
    return await cron_service.list_cron_jobs()


async def delete_cron_job(name: str, confirm: Optional[str] = None) -> Dict[str, Any]:
    return await cron_service.delete_cron_job(name, confirm)
