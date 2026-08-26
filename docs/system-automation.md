# System Automation & Background Schedulers

A comprehensive guide to scheduled tasks, background scanning loops, proactive reminders, and autonomous maintenance routines in the Mini Server Dashboard.

---

## 1. Background Schedulers Architecture

```mermaid
flowchart TD
    FastAPILifespan["FastAPI Lifespan Startup Event"] --> SpawnSchedulers["Spawn Async Background Tasks"]

    subgraph AsyncBackgroundWorkers["🔄 Async Background Worker Loops"]
        Loop1["1. Telegram Bot Poller\n• Long-polling Telegram API updates\n• Instant message delivery"]
        Loop2["2. Facebook Scanner Loop (3 min)\n• Playwright E2EE PIN unlock\n• Absence auto-reply & Unsend engine"]
        Loop3["3. TikTok Scanner Loop (3 min)\n• Automated DM scanner\n• Daily streak keeper routine"]
        Loop4["4. Appointment Reminder Loop (60s)\n• Scans facebook_appointments\n• Proactive 1h Telegram dispatch"]
        Loop5["5. RTK Stats Persistence Loop (30s)\n• Flushes pending token compression deltas\n• Updates rtk_stats in PostgreSQL"]
    end

    SpawnSchedulers --> Loop1
    SpawnSchedulers --> Loop2
    SpawnSchedulers --> Loop3
    SpawnSchedulers --> Loop4
    SpawnSchedulers --> Loop5

    subgraph TargetHostTimers["🐧 Remote Target Host Systemd Timers"]
        T1["apt-daily.timer (06:00 ICT)\nPackage index update (apt update)"]
        T2["apt-daily-upgrade.timer (06:00 ICT)\nSecurity package upgrade (apt upgrade)"]
    end
```

---

## 2. Mutex Lock Guard: Live noVNC Session vs. Background Scanner

To prevent Playwright profile corruption and browser lock contention when the user opens the visual noVNC console, a dedicated **Concurrency Guard** is enforced:

```mermaid
flowchart TD
    StartScan["Scheduled Scan Cycle Triggered (Facebook / TikTok)"] --> CheckVNC{"vnc_manager.is_running()?"}
    
    CheckVNC -- "Yes (User is active in noVNC)" --> LogSkip["Log: 'Live VNC session active; skipping scheduled scan cycle'\nDelay 20s & check again"]
    LogSkip --> EndCycle(["Wait for next interval"])
    
    CheckVNC -- "No (Browser available)" --> AcquireBrowser["Acquire Playwright Browser Context"]
    AcquireBrowser --> RunAutomation["Execute Inbox Scan / PIN Unlock / Streak Checks"]
    RunAutomation --> ReleaseBrowser["Release Browser Session & Update Database"]
    ReleaseBrowser --> EndCycle
```

---

## 3. Scheduler Specifications & Timing

| Scheduler Name | Execution Cadence | Primary Responsibilities | Target Database Tables |
| --- | --- | --- | --- |
| `telegram_task` | Continuous (Long Polling) | Inbound AI commands, sysadmin execution, alert delivery | `telegram_configs` |
| `fb_scan_task` | Every 3–15 min (Configurable) | E2EE PIN unlock, absence replies, auto-unsend on human reply | `facebook_config`, `facebook_known_threads` |
| `tiktok_scan_task` | Every 3–15 min (Configurable) | DM auto-reply, daily streak deadline keeper | `tiktok_config`, `tiktok_streaks` |
| `reminder_task` | Every 60 seconds | 1-hour proactive appointment alerts via Telegram | `facebook_appointments` |
| `rtk_persist_task` | Every 30 seconds | Persisting token compression savings to database | `rtk_stats` |
