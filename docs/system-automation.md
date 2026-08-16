# System Automation & Maintenance

A technical guide to automated OS patching, daily APT timers, automated cleanup policies, and Docker health-check self-healing.

---

## Overview

The target Linux server is configured with automated systemd background timers and APT cleanup rules to guarantee zero-touch security updates, kernel maintenance, and storage hygiene.

```text
┌────────────────────────────────────────────────────────────┐
│                  Linux Systemd Timers                      │
│                                                            │
│   06:00 AM ───▶ apt-daily.timer (apt update)               │
│                      │                                     │
│   06:30 AM ───▶ apt-daily-upgrade.timer (apt upgrade -y)   │
│                      │                                     │
│                      ▼                                     │
│   Post-Upgrade ──▶ /etc/apt/apt.conf.d/99auto-cleanup      │
│                    (autoremove & autoclean)                │
└────────────────────────────────────────────────────────────┘
```

---

## 1. Daily APT Systemd Timers

Ubuntu systemd timers control automatic package list updating and package upgrades.

### Configured Timers

| Timer Unit | Execution Schedule | Action Performed |
| --- | --- | --- |
| `apt-daily.timer` | Daily at **06:00:00 AM** | Runs `apt update` to fetch latest security package lists |
| `apt-daily-upgrade.timer` | Daily at **06:30:00 AM** | Runs `apt upgrade -y` to apply non-phased package patches |

### Systemd Timer Override Files

Location on remote server:

- `/etc/systemd/system/apt-daily.timer.d/override.conf`
- `/etc/systemd/system/apt-daily-upgrade.timer.d/override.conf`

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 06:00:00
RandomizedDelaySec=0
```

---

## 2. Automated Storage Cleanup Policy

To prevent `/var` or root disk partitions from filling up with old `.deb` archives and orphan kernel dependencies, an explicit APT auto-cleanup policy is configured at `/etc/apt/apt.conf.d/99auto-cleanup`:

```apt
APT::Periodic::AutocleanInterval "1";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
```

---

## 3. AI Agent Background Automation (`ai-agent-service`)

### 1. Periodic Inbox Scanner
- Runs as an asynchronous background worker in FastAPI.
- Scans active Facebook conversation threads every 60 seconds.
- Automatically decrypts and verifies new incoming messages.

### 2. Auto-Unsend Garbage Collection
- Automatically checks `facebook_known_threads` for pending unsend flags.
- If the owner has responded, it triggers the automated headless Playwright unsend routine without user intervention.

### 3. Chromium Headless Memory Hygiene
- Persistent IndexedDB storage ensures session survival without unbounded disk growth.
- Old screenshot debug artifacts in `/app/browser_data` are automatically pruned to prevent container volume bloat.
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
```

### What This Accomplishes

- **`AutocleanInterval "1"`:** Automatically runs `apt-get autoclean` after upgrades, clearing cached `.deb` files for uninstalled packages.
- **`Remove-Unused-Dependencies "true"`:** Automatically runs `apt-get autoremove`, stripping unneeded dependency packages.
- **`Remove-Unused-Kernel-Packages "true"`:** Purges old Linux kernel headers and images, freeing up `/boot` partition space.

---

## 3. Verifying System Automation Status

### Check Timer Schedules

```bash
sudo systemctl status apt-daily.timer apt-daily-upgrade.timer
```

### Inspect Last Execution Timestamps

```bash
# Check last successful apt update timestamp
stat /var/lib/apt/periodic/update-success-stamp

# Check recent apt upgrade history
grep -E 'Start-Date|Commandline' /var/log/apt/history.log | tail -n 20
```

---

## 4. Understanding Phased Updates (Ubuntu)

When running `apt upgrade` or asking the Telegram AI Agent for update status, you may see:
> *Not upgrading yet due to phasing: systemd, udev, cloud-init...*

**Reason:** Ubuntu uses **Phased Rollouts** for core system packages (`systemd`, `udev`, `grub2`). Updates are gradually deployed to percentages of servers over several days (e.g. 10% ➔ 50% ➔ 100%) to mitigate catastrophic bugs. `apt` automatically upgrades these packages once Canonical completes full rollout verification.
