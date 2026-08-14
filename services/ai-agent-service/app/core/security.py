from typing import List, Optional

BLOCKED_PATTERNS: List[str] = [
    # File destruction
    "rm ", "rm\t", "rmdir", "dd ", "shred", "wipefs", "truncate",
    # Disk / filesystem modifications
    "mkfs", "/dev/sda", "/dev/sdb", "/dev/nvme", "/dev/vd",
    # System shutdown / power
    "shutdown", "reboot", "poweroff", "halt", "init 0", "init 6",
    # Process termination
    "kill ", "kill\t", "pkill", "killall",
    # Dangerous systemctl operations
    "systemctl stop", "systemctl disable", "systemctl mask",
    "service stop", "service disable",
    # User / auth management
    "passwd", "adduser", "useradd", "userdel", "groupdel",
    "su ", "su\t", "sudo su",
    # Network / firewall destruction
    "iptables -f", "iptables --flush", "ufw disable", "ufw reset",
    # Package removal
    "apt remove", "apt purge", "apt-get remove", "apt-get purge",
    "yum remove", "yum erase", "dnf remove",
    "pip uninstall", "npm uninstall",
    # Docker destruction (read-only docker ps/logs/stats are OK)
    "docker rm", "docker rmi", "docker kill", "docker stop",
    "docker pause", "docker network rm", "docker volume rm",
    # File write redirects
    " > /", "\t> /", " >> /", "\t>> /",
    # Shell injection / arbitrary code execution
    "|bash", "| bash", "|sh", "| sh",
    ";bash", "; bash", ";sh", "; sh",
    "&bash", "& bash", "&sh", "& sh",
    "$(", "`",
    # Reverse shell / network abuse
    "nc ", "nc\t", "ncat", "netcat",
    "wget ", "curl -o ", "curl --output",
    # Inline interpreter execution
    "python -c", "python3 -c", "perl -e", "ruby -e", "node -e",
    # Cron removal
    "crontab -r",
]


def find_security_violation(command: Optional[str]) -> Optional[str]:
    """
    Checks whether a shell command contains any blocked destructive patterns.
    Returns the reason string if blocked, or None if safe.
    """
    if not command or not command.strip():
        return "empty command"

    lower = command.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return f"contains '{pattern.strip()}'"

    return None
