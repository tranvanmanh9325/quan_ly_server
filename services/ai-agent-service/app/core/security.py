from typing import List, Optional

# Hardware-destructive and unrecoverable physical wipe patterns (Spinal Safety Veto)
# These patterns destroy physical disks, partition tables, or the root filesystem.
# They are strictly blocked even in administrative/unrestricted mode unless explicitly authorized.
HARDWARE_DESTRUCTIVE_PATTERNS: List[str] = [
    # Disk / filesystem formatting and wipe
    "mkfs",
    "wipefs",
    "/dev/sda",
    "/dev/sdb",
    "/dev/nvme",
    "/dev/vd",
    # Raw block overwriting
    "dd of=/dev/",
    "dd if=/dev/zero of=/dev/",
    "dd if=/dev/urandom of=/dev/",
    # Unrecoverable root destruction
    "rm -rf /",
    "rm -rf /*",
    "rm -rf --no-preserve-root",
    "rm -fr /",
    "rm -fr /*",
    # Fork bombs that crash hardware kernel
    ":(){ :|:& };:",
]

# Standard blocked patterns for unprivileged or standard user commands
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


def is_hardware_destructive(command: Optional[str]) -> bool:
    """
    Checks if a command contains patterns that cause catastrophic or permanent
    hardware/filesystem destruction (e.g. formatting disks, overwriting partitions, rm -rf /).
    """
    if not command or not command.strip():
        return False
    lower = command.lower()
    return any(p in lower for p in HARDWARE_DESTRUCTIVE_PATTERNS)


def find_security_violation(
    command: Optional[str],
    allow_admin: bool = False,
    unrestricted: bool = False,
) -> Optional[str]:
    """
    Checks whether a shell command contains any blocked destructive patterns.
    
    When allow_admin or unrestricted is True:
      - Artificial administration barriers are lifted (allowing docker stop, systemctl,
        apt, pip, kill, subshells, pipes, and redirection).
      - Core spinal hardware safety veto remains active against physical disk format
        or unrecoverable root destruction (mkfs, /dev/sda, rm -rf /).
    
    When allow_admin and unrestricted are False (default):
      - Enforces full BLOCKED_PATTERNS check for defense-in-depth on user-facing commands.
    
    Returns the reason string if blocked, or None if safe.
    """
    if not command or not command.strip():
        return "empty command"

    lower = command.lower()

    if allow_admin or unrestricted:
        # In administrative / unrestricted mode, only veto catastrophic hardware/filesystem destruction
        for pattern in HARDWARE_DESTRUCTIVE_PATTERNS:
            if pattern in lower:
                return f"contains destructive hardware pattern '{pattern.strip()}'"
        return None

    # In standard mode, check standard blocked patterns
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return f"contains '{pattern.strip()}'"

    return None
