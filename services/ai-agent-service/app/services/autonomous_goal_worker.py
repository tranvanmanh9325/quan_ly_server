"""
AutonomousGoalWorker — True Autonomous AI Agent Goal Engine (R1).

Chịu trách nhiệm:
1. Tiếp nhận mục tiêu dài hạn (Autonomous Goals) và phân rã kế hoạch đa bước.
2. Lưu trữ kế hoạch và trạng thái bền vững (Persistence) qua PostgreSQL table `agent_tasks`.
3. Background polling loop (mặc định 30s) quét và thực thi tuần tự các bước thông qua `AgentToolExecutor`.
4. Cơ chế an toàn vi mạch (Spinal Safety Gating): Tự động thực thi Tier 1 & 2; Chặn lệnh Tier 3 Lethal và chuyển sang `waiting_approval`.
5. Báo cáo tiến trình chủ động (Proactive Telegram Notifications) khi hoàn thành hoặc gặp sự cố.
6. Hỗ trợ InMemoryTaskStore fallback cho môi trường test/dev độc lập.
"""

import asyncio
import html
import inspect
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.ai_agent_tools import (
    classify_action_risk,
    ACTION_TIER_3_LETHAL,
    ACTION_TIER_1_SAFE,
    ACTION_TIER_2_REVERSIBLE,
)

logger = logging.getLogger("app.services.autonomous_goal_worker")
VN_TZ = timezone(timedelta(hours=7))


class InMemoryTaskStore:
    """Fallback in-memory task repository for offline unit tests and disconnected mode."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def insert(self, task: Dict[str, Any]) -> None:
        async with self._lock:
            self._tasks[task["id"]] = dict(task)

    async def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            t = self._tasks.get(task_id)
            return dict(t) if t else None

    async def update(self, task: Dict[str, Any]) -> None:
        async with self._lock:
            task_id = str(task["id"])
            existing = self._tasks.get(task_id)
            new_task = dict(task)
            if existing:
                curr_status = existing.get("status")
                new_status = new_task.get("status")

                if curr_status in ("cancelled", "completed"):
                    new_task["status"] = curr_status
                    if curr_status == "completed":
                        new_task["error_message"] = existing.get("error_message")
                    elif existing.get("error_message"):
                        new_task["error_message"] = existing.get("error_message")
                    if existing.get("completed_at"):
                        new_task["completed_at"] = existing.get("completed_at")
                elif curr_status == "failed":
                    if new_status != "cancelled":
                        new_task["status"] = "failed"
                        if existing.get("error_message"):
                            new_task["error_message"] = existing.get("error_message")
                        if existing.get("completed_at"):
                            new_task["completed_at"] = existing.get("completed_at")
                elif curr_status == "waiting_approval":
                    if new_status not in ("cancelled", "failed"):
                        new_task["status"] = "waiting_approval"
                        if existing.get("error_message"):
                            new_task["error_message"] = existing.get("error_message")
                        if existing.get("completed_at"):
                            new_task["completed_at"] = existing.get("completed_at")
            self._tasks[task_id] = new_task

    async def save(self, task: Dict[str, Any]) -> None:
        """Alias for update, persisting task changes with status protection."""
        await self.update(task)

    async def list_pending_and_running(self, limit: int = 10) -> List[Dict[str, Any]]:
        async with self._lock:
            active = [
                dict(t)
                for t in self._tasks.values()
                if t.get("status") in ("pending", "running")
            ]
            active.sort(key=lambda x: str(x.get("created_at", "")))
            return active[:limit]

    async def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        async with self._lock:
            res = [
                dict(t)
                for t in self._tasks.values()
                if status is None or t.get("status") == status
            ]
            res.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
            return res[:limit]


class AutonomousGoalWorker:
    """
    Autonomous Goal Engine background worker.
    Manages persistent multi-step goal execution with risk classification and proactive Telegram reports.
    """

    def __init__(
        self,
        tool_executor: Optional[Any] = None,
        telegram_bot: Optional[Any] = None,
        llm_router: Optional[Any] = None,
        memory_service: Optional[Any] = None,
        pool: Optional[Any] = None,
        poll_interval_seconds: int = 30,
        use_db: bool = True,
    ) -> None:
        self.tool_executor = tool_executor
        self.telegram_bot = telegram_bot
        self.llm_router = llm_router
        self.memory_service = memory_service
        self.pool = pool
        self.poll_interval_seconds = poll_interval_seconds
        self.use_db = use_db

        self._in_memory_store = InMemoryTaskStore()
        self._running: bool = False
        self._worker_task: Optional[asyncio.Task] = None
        self._poll_lock = asyncio.Lock()

    @asynccontextmanager
    async def _get_conn(self):
        """Acquire a pooled DB connection or fail fast."""
        if self.pool is not None:
            async with self.pool.connection() as conn:
                yield conn
        else:
            from app.core.db import get_db_connection
            async with get_db_connection() as conn:
                yield conn

    def _normalize_row(self, row: Any) -> Dict[str, Any]:
        """Convert a DB row (dict or tuple) into a standard task dictionary."""
        if isinstance(row, dict):
            d = dict(row)
        else:
            d = {
                "id": str(row[0]),
                "goal": row[1],
                "steps": row[2],
                "current_step": row[3],
                "status": row[4],
                "trigger_condition": row[5],
                "chat_id": row[6],
                "result_json": row[7],
                "error_message": row[8],
                "retry_count": row[9],
                "max_retries": row[10],
                "created_at": str(row[11]) if row[11] else None,
                "updated_at": str(row[12]) if row[12] else None,
                "completed_at": str(row[13]) if row[13] else None,
            }
        if isinstance(d.get("steps"), str):
            try:
                d["steps"] = json.loads(d["steps"])
            except Exception:
                d["steps"] = []
        elif d.get("steps") is None:
            d["steps"] = []

        if isinstance(d.get("result_json"), str):
            try:
                d["result_json"] = json.loads(d["result_json"])
            except Exception:
                d["result_json"] = {}
        elif d.get("result_json") is None:
            d["result_json"] = {}
        return d

    async def ensure_tables(self) -> None:
        """
        Creates/verifies agent_tasks table and indexes (idempotent startup safety net).
        Falls back to InMemoryTaskStore if PostgreSQL is unavailable.
        """
        if not self.use_db:
            logger.info("[AutonomousGoalWorker] use_db=False, operating in InMemoryTaskStore mode.")
            return

        create_sql = """
        CREATE TABLE IF NOT EXISTS agent_tasks (
            id                  VARCHAR(64) PRIMARY KEY,
            goal                TEXT NOT NULL,
            steps               JSONB NOT NULL DEFAULT '[]'::jsonb,
            current_step        INT NOT NULL DEFAULT 0,
            status              VARCHAR(32) NOT NULL DEFAULT 'pending',
            trigger_condition   TEXT,
            chat_id             VARCHAR(64),
            result_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message       TEXT,
            retry_count         INT NOT NULL DEFAULT 0,
            max_retries         INT NOT NULL DEFAULT 3,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at        TIMESTAMPTZ
        );

        CREATE INDEX IF NOT EXISTS idx_agent_tasks_status 
            ON agent_tasks (status);

        CREATE INDEX IF NOT EXISTS idx_agent_tasks_active_poll 
            ON agent_tasks (status, created_at ASC);
        """
        try:
            async with self._get_conn() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(create_sql)
            logger.info("[AutonomousGoalWorker] PostgreSQL agent_tasks table verified/created ✓")
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] ensure_tables failed: %s. Falling back to InMemoryTaskStore.", e)
            self.use_db = False

    async def _save_task(self, task: Dict[str, Any], is_new: bool = False) -> None:
        """Persist task record to PostgreSQL or InMemoryTaskStore."""
        if not self.use_db:
            if is_new:
                await self._in_memory_store.insert(task)
            else:
                await self._in_memory_store.update(task)
            return

        upsert_sql = """
        INSERT INTO agent_tasks (
            id, goal, steps, current_step, status,
            trigger_condition, chat_id, result_json,
            error_message, retry_count, max_retries,
            created_at, updated_at, completed_at
        ) VALUES (
            %(id)s, %(goal)s, %(steps)s::jsonb, %(current_step)s, %(status)s,
            %(trigger_condition)s, %(chat_id)s, %(result_json)s::jsonb,
            %(error_message)s, %(retry_count)s, %(max_retries)s,
            %(created_at)s, %(updated_at)s, %(completed_at)s
        )
        ON CONFLICT (id) DO UPDATE SET
            steps = EXCLUDED.steps,
            current_step = EXCLUDED.current_step,
            status = CASE 
                WHEN agent_tasks.status IN ('cancelled', 'completed') THEN agent_tasks.status 
                WHEN agent_tasks.status = 'failed' AND EXCLUDED.status != 'cancelled' THEN agent_tasks.status 
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') THEN agent_tasks.status 
                ELSE EXCLUDED.status 
            END,
            result_json = EXCLUDED.result_json,
            error_message = CASE
                WHEN agent_tasks.status = 'completed' THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'cancelled' AND agent_tasks.error_message IS NOT NULL THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'failed' AND agent_tasks.error_message IS NOT NULL AND EXCLUDED.status != 'cancelled' THEN agent_tasks.error_message
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') AND agent_tasks.error_message IS NOT NULL THEN agent_tasks.error_message
                ELSE EXCLUDED.error_message
            END,
            retry_count = EXCLUDED.retry_count,
            updated_at = EXCLUDED.updated_at,
            completed_at = CASE
                WHEN agent_tasks.status IN ('cancelled', 'completed') AND agent_tasks.completed_at IS NOT NULL THEN agent_tasks.completed_at
                WHEN agent_tasks.status = 'failed' AND agent_tasks.completed_at IS NOT NULL AND EXCLUDED.status != 'cancelled' THEN agent_tasks.completed_at
                WHEN agent_tasks.status = 'waiting_approval' AND EXCLUDED.status NOT IN ('cancelled', 'failed') AND agent_tasks.completed_at IS NOT NULL THEN agent_tasks.completed_at
                ELSE EXCLUDED.completed_at
            END;
        """
        params = {
            "id": str(task["id"]),
            "goal": task["goal"],
            "steps": json.dumps(task.get("steps", [])),
            "current_step": int(task.get("current_step", 0)),
            "status": str(task.get("status", "pending")),
            "trigger_condition": task.get("trigger_condition"),
            "chat_id": task.get("chat_id"),
            "result_json": json.dumps(task.get("result_json", {})),
            "error_message": task.get("error_message"),
            "retry_count": int(task.get("retry_count", 0)),
            "max_retries": int(task.get("max_retries", 3)),
            "created_at": task.get("created_at") or datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "completed_at": task.get("completed_at"),
        }
        try:
            async with self._get_conn() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(upsert_sql, params)
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] _save_task DB write failed: %s. Falling back to memory store.", e)
            self.use_db = False
            if is_new:
                await self._in_memory_store.insert(task)
            else:
                await self._in_memory_store.update(task)

    async def _decompose_goal_with_llm(self, goal: str) -> List[Dict[str, Any]]:
        """Decompose a high-level natural language goal into executable sub-task steps."""
        if self.llm_router and hasattr(self.llm_router, "complete"):
            system_prompt = (
                "Bạn là Autonomous Goal Planner cho AI Agent Tiểu Bảo Bảo quản lý máy chủ Ubuntu.\n"
                "Nhiệm vụ: Phân rã mục tiêu của người dùng thành danh sách các bước tuần tự (sub-tasks).\n"
                "Chỉ trả về JSON Array các object bước theo cấu trúc:\n"
                "[\n"
                "  {\n"
                "    \"step_id\": 1,\n"
                "    \"tool\": \"tên công cụ (ví dụ: run_command, check_service_status, get_system_health_report)\",\n"
                "    \"args\": {\"command\": \"lệnh bash nếu là run_command\"},\n"
                "    \"verify\": \"điều kiện xác thực\"\n"
                "  }\n"
                "]\n"
                "QUAN TRỌNG: Chỉ trả về JSON thuần, không kèm markdown backticks hay giải thích."
            )
            try:
                if inspect.iscoroutinefunction(self.llm_router.complete):
                    resp = await self.llm_router.complete(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Mục tiêu cần phân rã: {goal}"},
                        ],
                        temperature=0.1,
                        max_tokens=600,
                    )
                else:
                    resp = self.llm_router.complete(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Mục tiêu cần phân rã: {goal}"},
                        ],
                        temperature=0.1,
                        max_tokens=600,
                    )
                if inspect.iscoroutine(resp):
                    resp = await resp

                if isinstance(resp, dict):
                    content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
                    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE).strip()
                    parsed = json.loads(content)
                    if isinstance(parsed, list) and len(parsed) > 0:
                        return parsed
            except Exception as e:
                logger.warning("[AutonomousGoalWorker] LLM goal decomposition error: %s. Using heuristic fallback.", e)

        # Heuristic fallback based on goal domain
        goal_lower = goal.lower()
        if any(w in goal_lower for w in ("disk", "ổ đĩa", "dung lượng", "dọn dẹp", "prune")):
            return [
                {"step_id": 1, "tool": "run_command", "args": {"command": "df -h"}, "verify": "disk_info_obtained"},
                {"step_id": 2, "tool": "get_system_health_report", "args": {}, "verify": "health_checked"},
            ]
        elif any(w in goal_lower for w in ("ram", "bộ nhớ", "memory")):
            return [
                {"step_id": 1, "tool": "run_command", "args": {"command": "free -m"}, "verify": "ram_info_obtained"}
            ]
        elif any(w in goal_lower for w in ("docker", "container")):
            return [
                {"step_id": 1, "tool": "run_command", "args": {"command": "docker ps"}, "verify": "containers_checked"}
            ]
        else:
            return [
                {"step_id": 1, "tool": "get_system_health_report", "args": {}, "verify": "system_diagnosed"}
            ]

    async def create_goal(
        self,
        goal: str,
        steps: Optional[List[Dict[str, Any]]] = None,
        trigger_condition: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> str:
        """
        Create a new autonomous goal.
        If steps are not provided, automatically decompose goal into structured steps.
        Returns the persistent task_id.
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        if steps is None:
            steps = await self._decompose_goal_with_llm(goal)

        normalized_steps: List[Dict[str, Any]] = []
        for idx, s in enumerate(steps):
            s_dict = dict(s)
            if "step_id" not in s_dict:
                s_dict["step_id"] = idx + 1
            if "status" not in s_dict:
                s_dict["status"] = "pending"
            normalized_steps.append(s_dict)

        now_iso = datetime.now(timezone.utc).isoformat()
        task_record: Dict[str, Any] = {
            "id": task_id,
            "goal": goal,
            "steps": normalized_steps,
            "current_step": 0,
            "status": "pending",
            "trigger_condition": trigger_condition,
            "chat_id": str(chat_id) if chat_id else None,
            "result_json": {},
            "error_message": None,
            "retry_count": 0,
            "max_retries": 3,
            "created_at": now_iso,
            "updated_at": now_iso,
            "completed_at": None,
        }

        await self._save_task(task_record, is_new=True)
        logger.info("[AutonomousGoalWorker] Goal created: id=%s, steps_count=%d", task_id, len(normalized_steps))
        return task_id

    async def get_goal_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch status and progress details of a goal by task_id."""
        task_id_str = str(task_id)
        if not self.use_db:
            return await self._in_memory_store.get(task_id_str)

        query = """
        SELECT id, goal, steps, current_step, status, trigger_condition, chat_id,
               result_json, error_message, retry_count, max_retries, created_at, updated_at, completed_at
        FROM agent_tasks
        WHERE id = %(id)s;
        """
        try:
            async with self._get_conn() as conn:
                from psycopg.rows import dict_row
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(query, {"id": task_id_str})
                    row = await cur.fetchone()
                    if row:
                        return self._normalize_row(row)
                    return None
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] get_goal_status DB read failed: %s. Falling back to memory.", e)
            return await self._in_memory_store.get(task_id_str)

    async def list_goals(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List autonomous goals with optional status filter."""
        if not self.use_db:
            return await self._in_memory_store.list_tasks(status=status, limit=limit)

        query = """
        SELECT id, goal, steps, current_step, status, trigger_condition, chat_id,
               result_json, error_message, retry_count, max_retries, created_at, updated_at, completed_at
        FROM agent_tasks
        """
        params: Dict[str, Any] = {"limit": limit}
        if status:
            query += " WHERE status = %(status)s"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT %(limit)s;"

        try:
            async with self._get_conn() as conn:
                from psycopg.rows import dict_row
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
                    return [self._normalize_row(r) for r in rows]
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] list_goals DB read failed: %s. Falling back to memory.", e)
            return await self._in_memory_store.list_tasks(status=status, limit=limit)

    async def cancel_goal(self, goal_id: str, reason: str = "User requested cancellation") -> bool:
        """Cancel an active or pending autonomous goal."""
        task = await self.get_goal_status(goal_id)
        if not task:
            return False

        if task.get("status") in ("completed", "failed", "cancelled"):
            return False

        task["status"] = "cancelled"
        task["error_message"] = reason
        task["completed_at"] = datetime.now(timezone.utc).isoformat()
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._save_task(task)
        logger.info("[AutonomousGoalWorker] Goal %s cancelled: %s", goal_id, reason)
        return True

    async def execute_pending_step(self, task_record: Dict[str, Any]) -> Dict[str, Any]:
        """Public alias for executing the current pending step of a task."""
        return await self._execute_single_step(task_record)

    async def _execute_single_step(self, task_record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute one pending step of a task:
        - Classify action risk (Tri-Tier Gating).
        - If Tier 3 Lethal: halt and transition to waiting_approval, send Telegram alert.
        - If Tier 1 or 2: execute tool via AgentToolExecutor.
        - Record result, advance current_step, or trigger retries on failure.
        - Send proactive Telegram notification on completion or final failure.
        """
        task_id = str(task_record["id"])
        latest_task = await self.get_goal_status(task_id)
        if latest_task:
            task_record.update(latest_task)

        goal = task_record.get("goal", "")
        status = task_record.get("status", "pending")
        steps = task_record.get("steps", [])
        current_step = int(task_record.get("current_step", 0))

        if status in ("completed", "failed", "cancelled", "waiting_approval"):
            return task_record

        if not steps or current_step >= len(steps):
            task_record["status"] = "completed"
            task_record["completed_at"] = datetime.now(timezone.utc).isoformat()
            task_record["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self._save_task(task_record)
            persisted_task = await self.get_goal_status(task_id)
            if persisted_task and persisted_task.get("status") == "completed":
                await self._notify_completion(persisted_task)
                return persisted_task
            return persisted_task or task_record

        step = steps[current_step]
        tool_name = step.get("tool") or step.get("tool_name", "")
        tool_args = step.get("args") or step.get("tool_args", {})

        if not tool_name and "command" in step:
            tool_name = "run_command"
            tool_args = {"command": step["command"]}
        if tool_args is None:
            tool_args = {}

        # ── Action Risk Tri-Tier Safety Gating ─────────────────────────────────
        risk_tier = classify_action_risk(tool_name, tool_args)
        if risk_tier == ACTION_TIER_3_LETHAL:
            step["status"] = "waiting_approval"
            task_record["status"] = "waiting_approval"
            task_record["error_message"] = f"Action {tool_name} requires confirmation token (Tier 3 Lethal)"
            task_record["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self._save_task(task_record)
            await self._notify_tier3_approval(task_record, tool_name, tool_args)
            logger.warning("[AutonomousGoalWorker] Task %s halted: Tier 3 Lethal action blocked (%s)", task_id, tool_name)
            return task_record

        # ── Execute Tool ───────────────────────────────────────────────────────
        try:
            if self.tool_executor:
                if inspect.iscoroutinefunction(self.tool_executor.execute_tool):
                    exec_result = await self.tool_executor.execute_tool(
                        tool_name, tool_args, chat_id=task_record.get("chat_id")
                    )
                else:
                    exec_result = self.tool_executor.execute_tool(tool_name, tool_args)
            else:
                exec_result = f"Simulated execution of {tool_name} with {tool_args}"

            # Re-check status from store/DB after awaiting tool execution
            latest_task = await self.get_goal_status(task_id)
            if latest_task and latest_task.get("status") in ("cancelled", "failed", "waiting_approval"):
                logger.info(
                    "[AutonomousGoalWorker] Task %s status changed to %s during tool execution; aborting step progression.",
                    task_id,
                    latest_task.get("status"),
                )
                return latest_task

            # Detect error string returned by executor
            is_error = False
            if isinstance(exec_result, str):
                low = exec_result.lower()
                if low.startswith("error:") or low.startswith("exception:") or "failed with exit code" in low:
                    is_error = True

            if is_error:
                raise RuntimeError(f"Tool {tool_name} returned error: {exec_result}")

            step["result"] = exec_result
            step["status"] = "completed"
            task_record["current_step"] = current_step + 1
            task_record["retry_count"] = 0
            task_record["updated_at"] = datetime.now(timezone.utc).isoformat()

            if task_record["current_step"] >= len(steps):
                task_record["status"] = "completed"
                task_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                task_record["result_json"] = {
                    "summary": f"Completed all {len(steps)} steps for goal: {goal}",
                    "steps": steps,
                }
                await self._save_task(task_record)
                persisted_task = await self.get_goal_status(task_id)
                if persisted_task and persisted_task.get("status") == "completed":
                    await self._notify_completion(persisted_task)
                    return persisted_task
                return persisted_task or task_record
            else:
                task_record["status"] = "running"
                await self._save_task(task_record)

            return task_record

        except Exception as exc:
            logger.error("[AutonomousGoalWorker] Step %d failed for task %s: %s", current_step + 1, task_id, exc)
            latest_task = await self.get_goal_status(task_id)
            if latest_task and latest_task.get("status") in ("cancelled", "failed", "waiting_approval", "completed"):
                logger.info(
                    "[AutonomousGoalWorker] Task %s status changed to %s during tool execution; aborting error handling.",
                    task_id,
                    latest_task.get("status"),
                )
                return latest_task

            retry_count = int(task_record.get("retry_count", 0)) + 1
            max_retries = int(task_record.get("max_retries", 3))
            task_record["retry_count"] = retry_count
            step["status"] = "failed"
            step["error"] = str(exc)
            task_record["updated_at"] = datetime.now(timezone.utc).isoformat()

            if retry_count >= max_retries:
                task_record["status"] = "failed"
                task_record["error_message"] = f"Failed at step {current_step + 1} ({tool_name}) after {retry_count} retries: {exc}"
                task_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                await self._save_task(task_record)
                await self._notify_failure(task_record)
            else:
                task_record["status"] = "running"
                task_record["error_message"] = f"Step {current_step + 1} ({tool_name}) error: {exc} (attempt {retry_count}/{max_retries})"
                await self._save_task(task_record)

            return task_record

    async def poll_once(self) -> int:
        """
        Perform a single polling cycle:
        Fetch up to 10 active tasks (status pending or running) and execute one step each.
        Returns the number of tasks processed.
        """
        async with self._poll_lock:
            active_tasks: List[Dict[str, Any]] = []
            if not self.use_db:
                active_tasks = await self._in_memory_store.list_pending_and_running(limit=10)
            else:
                query = """
                SELECT id, goal, steps, current_step, status, trigger_condition, chat_id,
                       result_json, error_message, retry_count, max_retries, created_at, updated_at, completed_at
                FROM agent_tasks
                WHERE status IN ('pending', 'running')
                ORDER BY created_at ASC
                LIMIT 10;
                """
                try:
                    async with self._get_conn() as conn:
                        from psycopg.rows import dict_row
                        async with conn.cursor(row_factory=dict_row) as cur:
                            await cur.execute(query)
                            rows = await cur.fetchall()
                            active_tasks = [self._normalize_row(r) for r in rows]
                except Exception as e:
                    logger.warning("[AutonomousGoalWorker] Polling query failed: %s. Falling back to memory.", e)
                    self.use_db = False
                    active_tasks = await self._in_memory_store.list_pending_and_running(limit=10)

            count = 0
            for task in active_tasks:
                try:
                    await self._execute_single_step(task)
                    count += 1
                except Exception as e:
                    logger.error("[AutonomousGoalWorker] Unexpected error executing task %s: %s", task.get("id"), e)
            return count

    async def _poll_and_execute_loop(self) -> None:
        """Background coroutine polling the tasks table every poll_interval_seconds."""
        logger.info("[AutonomousGoalWorker] Polling loop running (interval=%ds)", self.poll_interval_seconds)
        while self._running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[AutonomousGoalWorker] Error during polling cycle: %s", e)

            try:
                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start the background polling loop."""
        self._running = True
        await self._poll_and_execute_loop()

    def start_worker_loop(self) -> asyncio.Task:
        """Start polling loop as a detached background asyncio task."""
        self._running = True
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self.start())
        return self._worker_task

    async def stop(self) -> None:
        """Gracefully stop the background worker task with 5s timeout."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(self._worker_task), timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            self._worker_task = None
        logger.info("[AutonomousGoalWorker] Background worker stopped cleanly ✓")

    # ── Telegram Proactive Notification Helpers ───────────────────────────────

    def _get_target_chat_id(self, task_record: Dict[str, Any]) -> Optional[str]:
        """Resolve destination chat_id from task, telegram_bot, or settings."""
        if task_record.get("chat_id"):
            return str(task_record["chat_id"])
        if self.telegram_bot and getattr(self.telegram_bot, "chat_id", None):
            return str(self.telegram_bot.chat_id)
        if getattr(settings, "TELEGRAM_CHAT_ID", None):
            return str(settings.TELEGRAM_CHAT_ID)
        return None

    async def _notify_completion(self, task_record: Dict[str, Any]) -> None:
        """Send proactive Telegram summary when a goal reaches completed status."""
        if not self.telegram_bot:
            return
        chat_id = self._get_target_chat_id(task_record)
        if not chat_id:
            return

        goal = html.escape(str(task_record.get("goal", "")))
        steps = task_record.get("steps", [])
        vn_time = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")

        step_lines: List[str] = []
        for idx, s in enumerate(steps, 1):
            t_name = html.escape(str(s.get("tool") or s.get("tool_name", "unknown")))
            res_str = str(s.get("result", ""))
            # Truncate result snippet to 150 chars
            clean_res = html.escape(" ".join(res_str.split())[:150])
            step_lines.append(f"• Bước {idx}: <code>{t_name}</code> → {clean_res}")

        details = "\n".join(step_lines) if step_lines else "Tất cả các bước đã hoàn tất."

        msg = (
            f"🎯 <b>Tiểu Bảo Bảo — Hoàn thành mục tiêu tự động</b>\n\n"
            f"📌 <b>Mục tiêu:</b> {goal}\n"
            f"⏱️ <b>Thời gian:</b> {vn_time} (UTC+7)\n"
            f"📊 <b>Tiến độ:</b> Đã hoàn thành {len(steps)}/{len(steps)} bước.\n\n"
            f"📝 <b>Chi tiết kết quả:</b>\n{details}"
        )
        try:
            await self.telegram_bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] Failed to send completion Telegram notification: %s", e)

    async def _notify_failure(self, task_record: Dict[str, Any]) -> None:
        """Send proactive Telegram alert when a goal fails after max retries."""
        if not self.telegram_bot:
            return
        chat_id = self._get_target_chat_id(task_record)
        if not chat_id:
            return

        goal = html.escape(str(task_record.get("goal", "")))
        current_step = int(task_record.get("current_step", 0))
        steps = task_record.get("steps", [])
        step = steps[current_step] if current_step < len(steps) else {}
        tool_name = html.escape(str(step.get("tool") or step.get("tool_name", "unknown")))
        error_msg = html.escape(str(task_record.get("error_message", "Không rõ nguyên nhân")))

        msg = (
            f"⚠️ <b>Tiểu Bảo Bảo — Mục tiêu tự động gặp sự cố</b>\n\n"
            f"📌 <b>Mục tiêu:</b> {goal}\n"
            f"❌ <b>Thất bại tại bước {current_step + 1}:</b> <code>{tool_name}</code>\n"
            f"🚨 <b>Nguyên nhân:</b> {error_msg}\n\n"
            f"💡 <i>Em đã tạm dừng thực thi mục tiêu để đảm bảo an toàn cho máy chủ.</i>"
        )
        try:
            await self.telegram_bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] Failed to send failure Telegram notification: %s", e)

    async def _notify_tier3_approval(
        self, task_record: Dict[str, Any], tool_name: str, tool_args: Dict[str, Any]
    ) -> None:
        """Send urgent Telegram alert when a task encounters a Tier 3 Lethal Action."""
        if not self.telegram_bot:
            return
        chat_id = self._get_target_chat_id(task_record)
        if not chat_id:
            return

        goal = html.escape(str(task_record.get("goal", "")))
        current_step = int(task_record.get("current_step", 0))
        steps = task_record.get("steps", [])
        args_str = html.escape(json.dumps(tool_args, ensure_ascii=False))
        escaped_tool_name = html.escape(str(tool_name))

        msg = (
            f"🛑 <b>CẢNH BÁO AN TOÀN VI MẠCH (Tier 3 Lethal Action)</b>\n\n"
            f"📌 <b>Mục tiêu:</b> {goal}\n"
            f"⚠️ <b>Bước {current_step + 1}/{len(steps)}:</b> Yêu cầu lệnh phá hủy nguy hiểm!\n"
            f"🛠️ <b>Công cụ:</b> <code>{escaped_tool_name}</code>\n"
            f"📦 <b>Tham số:</b> <code>{args_str}</code>\n\n"
            f"<i>Hệ thống đã tự động dừng mục tiêu và chuyển sang trạng thái chờ phê duyệt. Vui lòng xác nhận qua Telegram nếu muốn tiếp tục.</i>"
        )
        try:
            await self.telegram_bot.send_message(chat_id, msg, parse_mode="HTML")
        except Exception as e:
            logger.warning("[AutonomousGoalWorker] Failed to send Tier 3 approval Telegram notification: %s", e)
