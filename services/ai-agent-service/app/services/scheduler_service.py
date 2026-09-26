"""
app/services/scheduler_service.py — Smart Calendar & Scheduler Service (R1).

Manages automated reminders and scheduling tasks for the AI Agent:
- schedule_reminder: Schedules a reminder with optional repeat ('daily', 'weekly', 'none').
- list_scheduled_reminders: Lists active pending reminders.
- cancel_reminder: Cancels a pending reminder by ID.

Storage Architecture:
- Primary Tier: PostgreSQL table `agent_pending_tasks` via `app.core.db.get_db_connection`.
- Fallback Tier: Thread-safe in-memory store with auto-increment IDs for resilient offline/degraded operation.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional

from app.core.db import get_db_connection

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
VALID_REPEAT_OPTIONS = {"none", "daily", "weekly"}


def _to_vn_str(dt: Optional[datetime]) -> Optional[str]:
    """Formats a datetime object to a readable Vietnam timezone string (UTC+7)."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S (UTC+7)")


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Formats a datetime object to standard ISO 8601 string."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class InMemoryReminderStore:
    """Thread-safe fallback in-memory store for reminders when database is unavailable."""

    def __init__(self, start_id: int = 1000):
        self._reminders: Dict[int, Dict[str, Any]] = {}
        self._counter: int = start_id
        self._lock = asyncio.Lock()

    async def add(
        self,
        message: str,
        delay_minutes: int,
        repeat: str,
        remind_at: datetime,
    ) -> Dict[str, Any]:
        async with self._lock:
            self._counter += 1
            reminder_id = self._counter
            created_at = datetime.now(timezone.utc)
            item = {
                "id": reminder_id,
                "task_summary": f"[REMINDER:{repeat.upper()}] {message}",
                "message": message,
                "delay_minutes": delay_minutes,
                "repeat": repeat,
                "remind_at": _to_iso(remind_at),
                "remind_at_vn": _to_vn_str(remind_at),
                "status": "pending",
                "created_at": _to_iso(created_at),
                "storage": "memory",
            }
            self._reminders[reminder_id] = item
            return item

    async def list_pending(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return [
                dict(item)
                for item in self._reminders.values()
                if item.get("status") == "pending"
            ]

    async def cancel(self, reminder_id: int) -> bool:
        async with self._lock:
            if reminder_id in self._reminders:
                if self._reminders[reminder_id].get("status") == "pending":
                    self._reminders[reminder_id]["status"] = "cancelled"
                    self._reminders[reminder_id]["completed_at"] = _to_iso(
                        datetime.now(timezone.utc)
                    )
                    return True
            return False

    async def get(self, reminder_id: int) -> Optional[Dict[str, Any]]:
        async with self._lock:
            item = self._reminders.get(reminder_id)
            return dict(item) if item else None

    async def complete(
        self, reminder_id: int, reschedule_next: bool = False
    ) -> Optional[Dict[str, Any]]:
        async with self._lock:
            item = self._reminders.get(reminder_id)
            if not item or item.get("status") != "pending":
                return None

            repeat = item.get("repeat", "none")
            now = datetime.now(timezone.utc)

            if reschedule_next and repeat in ("daily", "weekly"):
                interval_hours = 24 if repeat == "daily" else 24 * 7
                next_remind = now + timedelta(hours=interval_hours)
                item["remind_at"] = _to_iso(next_remind)
                item["remind_at_vn"] = _to_vn_str(next_remind)
                item["updated_at"] = _to_iso(now)
                return dict(item)
            else:
                item["status"] = "completed"
                item["completed_at"] = _to_iso(now)
                return dict(item)


class SchedulerService:
    """
    Core Service handling Smart Reminders & Scheduling.
    Persists data in `agent_pending_tasks` with graceful in-memory degradation.
    """

    def __init__(self, use_db: bool = True):
        self._use_db = use_db
        self._memory_store = InMemoryReminderStore()

    async def schedule_reminder(
        self,
        message: str,
        delay_minutes: int,
        repeat: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Schedules a reminder to trigger after `delay_minutes` minutes.
        Supports repeat='daily' | 'weekly' | 'none'.
        """
        # 1. Input sanitization & validation
        if not message or not str(message).strip():
            return {
                "status": "error",
                "message": "Nội dung nhắc nhở không được để trống.",
            }

        clean_message = str(message).strip()

        try:
            delay_minutes = int(delay_minutes)
        except (ValueError, TypeError):
            return {
                "status": "error",
                "message": f"Số phút chờ (delay_minutes) không hợp lệ: '{delay_minutes}'. Phải là số nguyên.",
            }

        if delay_minutes <= 0:
            return {
                "status": "error",
                "message": f"Số phút chờ (delay_minutes) phải lớn hơn 0 (nhận được: {delay_minutes}).",
            }

        norm_repeat = (repeat or "none").strip().lower()
        if norm_repeat not in VALID_REPEAT_OPTIONS:
            return {
                "status": "error",
                "message": (
                    f"Tần suất lặp '{repeat}' không hợp lệ. "
                    f"Chỉ hỗ trợ: {', '.join(sorted(VALID_REPEAT_OPTIONS))}."
                ),
            }

        now_utc = datetime.now(timezone.utc)
        remind_at = now_utc + timedelta(minutes=delay_minutes)
        task_summary = f"[REMINDER:{norm_repeat.upper()}] {clean_message}"

        metadata = {
            "type": "reminder",
            "message": clean_message,
            "delay_minutes": delay_minutes,
            "repeat": norm_repeat,
            "created_at": _to_iso(now_utc),
        }
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        # 2. Attempt Database persistence
        if self._use_db:
            try:
                async with get_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO agent_pending_tasks
                                (task_summary, created_by_msg, remind_at, status)
                            VALUES (%s, %s, %s, 'pending')
                            RETURNING id, created_at
                            """,
                            (task_summary, metadata_json, remind_at),
                        )
                        row = await cur.fetchone()
                        if row:
                            task_id = row[0]
                            logger.info(
                                "[SchedulerService] DB reminder scheduled: #%d at %s (repeat=%s)",
                                task_id,
                                remind_at.isoformat(),
                                norm_repeat,
                            )
                            return {
                                "status": "success",
                                "reminder_id": task_id,
                                "message": clean_message,
                                "delay_minutes": delay_minutes,
                                "repeat": norm_repeat,
                                "remind_at": _to_iso(remind_at),
                                "remind_at_vn": _to_vn_str(remind_at),
                                "storage": "database",
                                "text": (
                                    f"⏰ Đã đặt lịch nhắc thành công (Mã #{task_id}): "
                                    f"\"{clean_message}\" sau {delay_minutes} phút (lúc {_to_vn_str(remind_at)})."
                                    + (f" Lặp lại: {norm_repeat}." if norm_repeat != "none" else "")
                                ),
                            }
            except Exception as exc:
                logger.warning(
                    "[SchedulerService] Database insert failed (%s). Engaging in-memory fallback...",
                    exc,
                )

        # 3. Fallback to In-Memory store
        mem_item = await self._memory_store.add(
            message=clean_message,
            delay_minutes=delay_minutes,
            repeat=norm_repeat,
            remind_at=remind_at,
        )
        task_id = mem_item["id"]
        logger.info(
            "[SchedulerService] In-memory reminder scheduled: #%d at %s (repeat=%s)",
            task_id,
            remind_at.isoformat(),
            norm_repeat,
        )
        return {
            "status": "success",
            "reminder_id": task_id,
            "message": clean_message,
            "delay_minutes": delay_minutes,
            "repeat": norm_repeat,
            "remind_at": _to_iso(remind_at),
            "remind_at_vn": _to_vn_str(remind_at),
            "storage": "memory",
            "text": (
                f"⏰ Đã đặt lịch nhắc thành công (Bộ nhớ tạm #{task_id}): "
                f"\"{clean_message}\" sau {delay_minutes} phút (lúc {_to_vn_str(remind_at)})."
                + (f" Lặp lại: {norm_repeat}." if norm_repeat != "none" else "")
            ),
        }

    async def list_scheduled_reminders(self) -> Dict[str, Any]:
        """
        Lists all active/pending reminders from database and in-memory store.
        """
        reminders: List[Dict[str, Any]] = []
        seen_ids = set()

        # 1. Fetch from Database
        if self._use_db:
            try:
                async with get_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT id, task_summary, created_by_msg, remind_at, status, created_at
                            FROM agent_pending_tasks
                            WHERE status = 'pending' AND remind_at IS NOT NULL
                            ORDER BY remind_at ASC
                            LIMIT 50
                            """
                        )
                        rows = await cur.fetchall()
                        for row in rows:
                            r_id, summary, meta_str, r_at, status, c_at = row
                            seen_ids.add(r_id)

                            message = summary
                            repeat = "none"
                            delay_minutes = 0

                            if meta_str:
                                try:
                                    meta = json.loads(meta_str)
                                    if isinstance(meta, dict):
                                        message = meta.get("message", summary)
                                        repeat = meta.get("repeat", "none")
                                        delay_minutes = meta.get("delay_minutes", 0)
                                except Exception:
                                    pass

                            reminders.append(
                                {
                                    "id": r_id,
                                    "message": message,
                                    "task_summary": summary,
                                    "repeat": repeat,
                                    "delay_minutes": delay_minutes,
                                    "remind_at": _to_iso(r_at),
                                    "remind_at_vn": _to_vn_str(r_at),
                                    "status": status,
                                    "created_at": _to_iso(c_at),
                                    "storage": "database",
                                }
                            )
            except Exception as exc:
                logger.warning("[SchedulerService] Database select error: %s", exc)

        # 2. Fetch from In-Memory Store
        mem_items = await self._memory_store.list_pending()
        for item in mem_items:
            if item["id"] not in seen_ids:
                reminders.append(item)

        # 3. Sort by remind_at timestamp
        def _sort_key(r: Dict[str, Any]) -> str:
            return r.get("remind_at") or ""

        reminders.sort(key=_sort_key)

        return {
            "status": "success",
            "total": len(reminders),
            "reminders": reminders,
        }

    async def cancel_reminder(self, reminder_id: int) -> Dict[str, Any]:
        """
        Cancels a scheduled reminder by its integer ID.
        Checks both database and in-memory store.
        """
        try:
            reminder_id = int(reminder_id)
        except (ValueError, TypeError):
            return {
                "status": "error",
                "message": f"Mã nhắc nhở (reminder_id) không hợp lệ: '{reminder_id}'. Phải là số nguyên.",
            }

        # 1. Try DB cancellation
        if self._use_db:
            try:
                async with get_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE agent_pending_tasks
                            SET status = 'cancelled', completed_at = NOW()
                            WHERE id = %s AND status = 'pending'
                            """,
                            (reminder_id,),
                        )
                        if cur.rowcount > 0:
                            logger.info("[SchedulerService] DB reminder #%d cancelled.", reminder_id)
                            return {
                                "status": "success",
                                "reminder_id": reminder_id,
                                "message": f"Đã hủy lịch nhắc nhở #{reminder_id} thành công.",
                            }
            except Exception as exc:
                logger.warning("[SchedulerService] DB cancel error: %s", exc)

        # 2. Try In-Memory cancellation
        if await self._memory_store.cancel(reminder_id):
            logger.info("[SchedulerService] In-memory reminder #%d cancelled.", reminder_id)
            return {
                "status": "success",
                "reminder_id": reminder_id,
                "message": f"Đã hủy lịch nhắc nhở #{reminder_id} (bộ nhớ tạm) thành công.",
            }

        return {
            "status": "not_found",
            "reminder_id": reminder_id,
            "message": f"Không tìm thấy lịch nhắc nhở #{reminder_id} ở trạng thái đang chờ (pending).",
        }

    async def get_due_reminders(self) -> List[Dict[str, Any]]:
        """
        Retrieves all reminders whose scheduled time has passed (due for trigger).
        Used by proactive background workers to deliver notifications.
        """
        due_items: List[Dict[str, Any]] = []
        now_utc = datetime.now(timezone.utc)

        if self._use_db:
            try:
                async with get_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT id, task_summary, created_by_msg, remind_at, status, created_at
                            FROM agent_pending_tasks
                            WHERE status = 'pending'
                              AND remind_at IS NOT NULL
                              AND remind_at <= NOW()
                            ORDER BY remind_at ASC
                            """
                        )
                        rows = await cur.fetchall()
                        for row in rows:
                            r_id, summary, meta_str, r_at, status, c_at = row
                            message = summary
                            repeat = "none"
                            if meta_str:
                                try:
                                    meta = json.loads(meta_str)
                                    if isinstance(meta, dict):
                                        message = meta.get("message", summary)
                                        repeat = meta.get("repeat", "none")
                                except Exception:
                                    pass
                            due_items.append(
                                {
                                    "id": r_id,
                                    "message": message,
                                    "task_summary": summary,
                                    "repeat": repeat,
                                    "remind_at": _to_iso(r_at),
                                    "remind_at_vn": _to_vn_str(r_at),
                                    "status": status,
                                    "storage": "database",
                                }
                            )
            except Exception as exc:
                logger.warning("[SchedulerService] DB due reminders query error: %s", exc)

        # In-memory due items
        mem_pending = await self._memory_store.list_pending()
        for item in mem_pending:
            r_at_str = item.get("remind_at")
            if r_at_str:
                try:
                    dt = datetime.fromisoformat(r_at_str)
                    if dt <= now_utc:
                        due_items.append(item)
                except Exception:
                    pass

        return due_items

    async def mark_reminder_dispatched(self, reminder_id: int) -> bool:
        """
        Marks a reminder as triggered/dispatched.
        If repeat is 'daily' or 'weekly', automatically schedules the next occurrence.
        """
        now_utc = datetime.now(timezone.utc)

        if self._use_db:
            try:
                async with get_db_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "SELECT created_by_msg, remind_at FROM agent_pending_tasks WHERE id = %s AND status = 'pending'",
                            (reminder_id,),
                        )
                        row = await cur.fetchone()
                        if row:
                            meta_str, r_at = row
                            repeat = "none"
                            if meta_str:
                                try:
                                    meta = json.loads(meta_str)
                                    repeat = meta.get("repeat", "none")
                                except Exception:
                                    pass

                            if repeat in ("daily", "weekly"):
                                hours = 24 if repeat == "daily" else 24 * 7
                                next_time = now_utc + timedelta(hours=hours)
                                await cur.execute(
                                    """
                                    UPDATE agent_pending_tasks
                                    SET remind_at = %s, turns_elapsed = 0
                                    WHERE id = %s
                                    """,
                                    (next_time, reminder_id),
                                )
                                logger.info(
                                    "[SchedulerService] Rescheduled repeat reminder #%d to %s",
                                    reminder_id,
                                    next_time.isoformat(),
                                )
                            else:
                                await cur.execute(
                                    """
                                    UPDATE agent_pending_tasks
                                    SET status = 'done', completed_at = NOW()
                                    WHERE id = %s
                                    """,
                                    (reminder_id,),
                                )
                            return True
            except Exception as exc:
                logger.warning("[SchedulerService] DB mark dispatched error: %s", exc)

        res = await self._memory_store.complete(reminder_id, reschedule_next=True)
        return res is not None


# Global singleton instance
_default_scheduler = SchedulerService()


# Module-level API satisfying Interface Contracts
async def schedule_reminder(
    message: str,
    delay_minutes: int,
    repeat: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Schedules an automated reminder.
    Interface contract: schedule_reminder(message: str, delay_minutes: int, repeat: Optional[str] = None) -> Dict[str, Any]
    """
    return await _default_scheduler.schedule_reminder(
        message=message,
        delay_minutes=delay_minutes,
        repeat=repeat,
    )


async def list_scheduled_reminders() -> Dict[str, Any]:
    """
    Lists all active pending reminders.
    Interface contract: list_scheduled_reminders() -> Dict[str, Any]
    """
    return await _default_scheduler.list_scheduled_reminders()


async def cancel_reminder(reminder_id: int) -> Dict[str, Any]:
    """
    Cancels a pending reminder by ID.
    Interface contract: cancel_reminder(reminder_id: int) -> Dict[str, Any]
    """
    return await _default_scheduler.cancel_reminder(reminder_id=reminder_id)


__all__ = [
    "SchedulerService",
    "schedule_reminder",
    "list_scheduled_reminders",
    "cancel_reminder",
]
