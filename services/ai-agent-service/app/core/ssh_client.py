import asyncio
import logging
import asyncssh
from app.config import settings
from app.core.security import find_security_violation

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT_SEC = 15
MAX_OUTPUT_CHARS = 1000


class SshClient:
    def __init__(self):
        self.host = settings.SSH_HOST
        self.port = settings.SSH_PORT
        self.user = settings.SSH_USER
        self.password = settings.SSH_PASSWORD
        self.fallback_host = settings.SSH_FALLBACK_HOST
        self.fallback_port = settings.SSH_FALLBACK_PORT

    async def execute_command(self, command: str) -> str:
        """
        Executes a shell command over SSH with security validation and timeout.
        """
        violation = find_security_violation(command)
        if violation:
            logger.warning("[SSH] BLOCKED command '%s' — %s", command, violation)
            return (
                f"BLOCKED: Lệnh bị từ chối vì lý do bảo mật ({violation}). "
                "Chỉ được phép dùng các lệnh đọc (ps, docker ps, free, df, cat, date, v.v.)"
            )

        # Connect with primary host, or fallback host if primary fails
        for host, port in [(self.host, self.port), (self.fallback_host, self.fallback_port)]:
            if not host:
                continue
            try:
                timed_cmd = f"timeout {COMMAND_TIMEOUT_SEC} {command}"
                logger.info("[SSH] Executing on %s:%d: %s", host, port, timed_cmd)

                async with asyncssh.connect(
                    host,
                    port=port,
                    username=self.user,
                    password=self.password,
                    known_hosts=None,
                    client_keys=None,
                ) as conn:
                    result = await asyncio.wait_for(
                        conn.run(timed_cmd, check=False),
                        timeout=COMMAND_TIMEOUT_SEC + 5,
                    )
                    stdout_raw = result.stdout or ""
                    stdout_str = stdout_raw.decode("utf-8", errors="replace") if isinstance(stdout_raw, bytes) else stdout_raw

                    stderr_raw = result.stderr or ""
                    stderr_str = stderr_raw.decode("utf-8", errors="replace") if isinstance(stderr_raw, bytes) else stderr_raw

                    stdout = stdout_str.strip()
                    stderr = stderr_str.strip()
                    output: str = stdout if stdout else stderr

                    if not output:
                        return "(lệnh không có output hoặc server không phản hồi)"

                    if len(output) > MAX_OUTPUT_CHARS:
                        output = output[:MAX_OUTPUT_CHARS] + "\n... [output bị cắt ngắn]"

                    return output

            except Exception as e:
                logger.warning("[SSH] Failed connecting to %s:%d: %s", host, port, str(e))
                if host == self.fallback_host or not self.fallback_host:
                    return f"Lỗi SSH khi thực thi lệnh: {e}"

        return "Không thể kết nối SSH tới máy chủ."
