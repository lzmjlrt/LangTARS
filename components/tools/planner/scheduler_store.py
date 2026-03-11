# Scheduler persistence - JSON-based storage for scheduled tasks
# Follows the same atomic-write pattern as memory.py

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A single scheduled task record"""
    task_id: str = ""
    task_type: str = "reminder"       # "reminder" | "execute"
    description: str = ""
    schedule_type: str = "delay"      # "delay" | "absolute" | "cron"

    # Timing
    next_run_ts: float = 0.0          # Next run epoch timestamp
    cron_expr: str = ""               # For cron tasks, e.g. "0 9 * * *"

    # Messaging context (needed for proactive send_message)
    bot_uuid: str = ""
    target_type: str = ""             # "group" | "person" etc.
    target_id: str = ""
    user_id: str = ""                 # Who scheduled it

    # State
    status: str = "active"            # "active" | "completed" | "cancelled" | "failed"
    created_ts: float = 0.0
    last_run_ts: float = 0.0
    run_count: int = 0
    max_runs: int = 1                 # 0 = unlimited (for cron), 1 for one-shot
    error_message: str = ""

    def __post_init__(self):
        if not self.task_id:
            self.task_id = uuid.uuid4().hex[:12]
        if self.created_ts == 0.0:
            self.created_ts = time.time()


class SchedulerStore:
    """
    Persistent storage for scheduled tasks.
    Uses atomic JSON writes (tmp + os.replace) following the PlannerMemory pattern.
    """

    def __init__(self, store_dir: str | None = None):
        if store_dir:
            self._store_dir = store_dir
        else:
            self._store_dir = str(Path.home() / ".langtars" / "scheduler")
        self._store_file = os.path.join(self._store_dir, "tasks.json")
        self._tasks: dict[str, ScheduledTask] = {}
        self._loaded = False

    def _load(self) -> None:
        """Load tasks from JSON file"""
        if self._loaded:
            return
        self._loaded = True

        if not os.path.exists(self._store_file):
            return

        try:
            with open(self._store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data.get("tasks", []):
                task = ScheduledTask(**entry)
                self._tasks[task.task_id] = task
            logger.info(f"已加载 {len(self._tasks)} 个定时任务")
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning(f"加载定时任务失败: {e}")
            self._tasks = {}

    def _save(self) -> None:
        """Atomic save: write to .tmp then os.replace"""
        data = {
            "version": 1,
            "tasks": [asdict(t) for t in self._tasks.values()],
        }
        tmp_path = self._store_file + ".tmp"
        try:
            os.makedirs(self._store_dir, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._store_file)
        except OSError as e:
            logger.warning(f"保存定时任务失败: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def add_task(self, task: ScheduledTask) -> None:
        """Add a new scheduled task"""
        self._load()
        self._tasks[task.task_id] = task
        self._save()
        logger.info(f"添加定时任务: {task.task_id} ({task.description[:50]})")

    def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID"""
        self._load()
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save()
            return True
        return False

    def update_task(self, task: ScheduledTask) -> None:
        """Update an existing task"""
        self._load()
        self._tasks[task.task_id] = task
        self._save()

    def get_task(self, task_id: str) -> ScheduledTask | None:
        """Get a task by ID"""
        self._load()
        return self._tasks.get(task_id)

    def get_active_tasks(self) -> list[ScheduledTask]:
        """Get all active tasks"""
        self._load()
        return [t for t in self._tasks.values() if t.status == "active"]

    def get_due_tasks(self, now: float | None = None) -> list[ScheduledTask]:
        """Get all active tasks that are due for execution"""
        if now is None:
            now = time.time()
        self._load()
        return [
            t for t in self._tasks.values()
            if t.status == "active" and t.next_run_ts <= now
        ]

    def get_tasks_for_user(self, user_id: str) -> list[ScheduledTask]:
        """Get all active tasks for a specific user"""
        self._load()
        return [
            t for t in self._tasks.values()
            if t.user_id == user_id and t.status == "active"
        ]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by marking it as cancelled"""
        self._load()
        task = self._tasks.get(task_id)
        if task and task.status == "active":
            task.status = "cancelled"
            self._save()
            return True
        return False

    def cleanup_old_tasks(self, max_age_days: int = 7) -> int:
        """Remove completed/cancelled/failed tasks older than max_age_days"""
        self._load()
        cutoff = time.time() - max_age_days * 86400
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.status in ("completed", "cancelled", "failed")
            and t.created_ts < cutoff
        ]
        for tid in to_remove:
            del self._tasks[tid]
        if to_remove:
            self._save()
        return len(to_remove)
