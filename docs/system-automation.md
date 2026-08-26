# System Automation & Background Schedulers

A comprehensive guide to scheduled tasks, background scanning loops, proactive reminders, and autonomous maintenance routines in the Mini Server Dashboard.

---

## 1. Background Schedulers Architecture

The `ai-agent-service` maintains dedicated asynchronous background loops managed by FastAPI lifespan events:

```text
FastAPI Lifespan Startup
    │
    ├── 1. Telegram Poller Loop (Long polling Telegram API)
    ├── 2. Facebook Scanner Loop (Periodic inbox scan & absence reply)
    ├── 3. TikTok Scanner & Streak Keeper Loop (Periodic DM check & daily streak send)
    ├── 4. Appointment Reminder Loop (1-hour proactive dispatch)
    └── 5. RTK Stats Persistence Loop (Persists compression stats to DB every 30s)
```

---

## 2. Scheduler Details

### 1. Facebook Messenger Scan Loop (`facebook_periodic_scan_loop`)
- **Interval:** Configurable from database (default: 3 minutes).
- **VNC Concurrency Guard:** Pauses automatic scan cycles when an active live noVNC session is detected to prevent browser lock contention.
- **Operations:** Scans unread chats, handles 6-digit E2EE PIN unlock, sends absence auto-replies, and executes automated message unsend when human owner replies.

### 2. TikTok Streak Keeper Loop (`tiktok_periodic_scan_loop`)
- **Interval:** Configurable from database (default: 3 minutes).
- **Streak Maintenance:** Checks daily streak deadlines and sends automated interaction messages.

### 3. Proactive Appointment Reminder Loop (`appointment_reminder_loop`)
- **Interval:** Runs every 60 seconds.
- **Proactive Notification:** Queries upcoming appointments from `facebook_appointments` and dispatches a high-priority Telegram alert exactly 1 hour before scheduled time.

### 4. RTK Stats Persistence Loop (`rtk_stats_persist_loop`)
- **Interval:** Runs every 30 seconds.
- **Delta Persistence:** Saves token compression counters to table `rtk_stats` only when deltas exist.

---

## 3. Remote Server Maintenance Timers

The system monitors and respects standard Linux Systemd Timers on the target machine:
- `apt-daily.timer`: Scheduled daily at 06:00 (ICT) for package index updates (`apt update`).
- `apt-daily-upgrade.timer`: Scheduled daily at 06:00 (ICT) for package security upgrades (`apt upgrade`).
