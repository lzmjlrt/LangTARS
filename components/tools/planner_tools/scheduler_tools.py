# Scheduler LLM tools - Tools that LLM can call to manage scheduled tasks
# Follows BasePlannerTool pattern

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from . import BasePlannerTool


class ScheduleTaskTool(BasePlannerTool):
    """Schedule a task to be executed at a future time."""

    @property
    def name(self) -> str:
        return "schedule_task"

    @property
    def description(self) -> str:
        return (
            "Schedule a task to be executed at a future time. "
            "Can schedule reminders (send a message) or execute tasks (run through AI agent). "
            "Supports delay (e.g. 120 seconds), absolute time (ISO 8601), "
            "or cron expression (e.g. '0 9 * * *' for every day at 9 AM)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["reminder", "execute"],
                    "description": "Type of task: 'reminder' sends a message at the scheduled time, 'execute' runs through the AI agent to perform a task"
                },
                "description": {
                    "type": "string",
                    "description": "What to remind the user or what task to execute"
                },
                "schedule_type": {
                    "type": "string",
                    "enum": ["delay", "absolute", "cron"],
                    "description": "How to schedule: 'delay' (relative seconds from now), 'absolute' (specific datetime), 'cron' (recurring cron expression)"
                },
                "delay_seconds": {
                    "type": "number",
                    "description": "For 'delay' schedule_type: number of seconds from now. E.g. 120 for 2 minutes"
                },
                "absolute_time": {
                    "type": "string",
                    "description": "For 'absolute' schedule_type: ISO 8601 datetime string, e.g. '2024-01-15T15:00:00'"
                },
                "cron_expression": {
                    "type": "string",
                    "description": "For 'cron' schedule_type: cron expression, e.g. '0 9 * * *' (every day at 9 AM), '*/30 * * * *' (every 30 minutes)"
                },
            },
            "required": ["task_type", "description", "schedule_type"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        from components.commands.langtars import BackgroundTaskManager
        from components.tools.planner.scheduler import TaskScheduler
        from components.tools.planner.scheduler_store import ScheduledTask

        task_type = arguments.get("task_type", "reminder")
        description = arguments.get("description", "")
        schedule_type = arguments.get("schedule_type", "delay")

        if not description:
            return {"success": False, "error": "description is required"}

        # Get messaging context from BackgroundTaskManager (set during task execution)
        bot_uuid = BackgroundTaskManager._bot_uuid or ""
        target_type = BackgroundTaskManager._target_type or ""
        target_id = str(BackgroundTaskManager._target_id or "")

        if not bot_uuid:
            return {"success": False, "error": "无法获取消息上下文，无法调度任务"}

        # Get current user ID
        user_id = "default"
        if hasattr(BackgroundTaskManager, '_current_user_id') and BackgroundTaskManager._current_user_id:
            user_id = BackgroundTaskManager._current_user_id

        # Compute next_run_ts
        now = time.time()
        next_run_ts = 0.0
        cron_expr = ""
        max_runs = 1  # default: one-shot

        if schedule_type == "delay":
            delay = arguments.get("delay_seconds")
            if not delay or delay <= 0:
                return {"success": False, "error": "delay_seconds must be a positive number"}
            next_run_ts = now + float(delay)

        elif schedule_type == "absolute":
            abs_time = arguments.get("absolute_time", "")
            if not abs_time:
                return {"success": False, "error": "absolute_time is required for 'absolute' schedule_type"}
            try:
                dt = datetime.fromisoformat(abs_time)
                next_run_ts = dt.timestamp()
                if next_run_ts <= now:
                    return {"success": False, "error": f"absolute_time {abs_time} is in the past"}
            except ValueError as e:
                return {"success": False, "error": f"Invalid absolute_time format: {e}"}

        elif schedule_type == "cron":
            cron_expr = arguments.get("cron_expression", "")
            if not cron_expr:
                return {"success": False, "error": "cron_expression is required for 'cron' schedule_type"}
            try:
                from croniter import croniter
                cron = croniter(cron_expr, datetime.now())
                next_run_ts = cron.get_next(float)
                max_runs = 0  # unlimited for cron
            except Exception as e:
                return {"success": False, "error": f"Invalid cron expression: {e}"}
        else:
            return {"success": False, "error": f"Unknown schedule_type: {schedule_type}"}

        # Create and store the task
        task = ScheduledTask(
            task_type=task_type,
            description=description,
            schedule_type=schedule_type,
            next_run_ts=next_run_ts,
            cron_expr=cron_expr,
            bot_uuid=bot_uuid,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            max_runs=max_runs,
        )

        scheduler = TaskScheduler.get_instance()
        scheduler.store.add_task(task)

        # Format human-readable time
        run_time = datetime.fromtimestamp(next_run_ts).strftime("%Y-%m-%d %H:%M:%S")
        type_desc = "提醒" if task_type == "reminder" else "执行任务"

        result = {
            "success": True,
            "task_id": task.task_id,
            "task_type": task_type,
            "schedule_type": schedule_type,
            "next_run_time": run_time,
            "description": description,
            "message": f"已创建定时{type_desc}，将在 {run_time} 执行",
        }
        if cron_expr:
            result["cron_expression"] = cron_expr
            result["message"] += f" (周期: {cron_expr})"

        return result


class ListScheduledTasksTool(BasePlannerTool):
    """List all active scheduled tasks for the current user."""

    @property
    def name(self) -> str:
        return "list_scheduled_tasks"

    @property
    def description(self) -> str:
        return "List all active scheduled tasks for the current user. Shows task ID, type, description, and next run time."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        from components.commands.langtars import BackgroundTaskManager
        from components.tools.planner.scheduler import TaskScheduler

        user_id = "default"
        if hasattr(BackgroundTaskManager, '_current_user_id') and BackgroundTaskManager._current_user_id:
            user_id = BackgroundTaskManager._current_user_id

        scheduler = TaskScheduler.get_instance()
        tasks = scheduler.store.get_tasks_for_user(user_id)

        if not tasks:
            # Also try getting all active tasks if user_id is default
            if user_id == "default":
                tasks = scheduler.store.get_active_tasks()

        if not tasks:
            return {"success": True, "tasks": [], "message": "没有活跃的定时任务"}

        task_list = []
        for t in tasks:
            next_time = datetime.fromtimestamp(t.next_run_ts).strftime("%Y-%m-%d %H:%M:%S")
            type_desc = "提醒" if t.task_type == "reminder" else "执行任务"
            schedule_desc = {
                "delay": "延迟",
                "absolute": "定时",
                "cron": f"周期 ({t.cron_expr})",
            }.get(t.schedule_type, t.schedule_type)

            task_list.append({
                "task_id": t.task_id,
                "type": type_desc,
                "schedule": schedule_desc,
                "description": t.description[:100],
                "next_run_time": next_time,
                "run_count": t.run_count,
            })

        return {
            "success": True,
            "tasks": task_list,
            "count": len(task_list),
            "message": f"共有 {len(task_list)} 个活跃的定时任务",
        }


class CancelScheduledTaskTool(BasePlannerTool):
    """Cancel a scheduled task by its ID."""

    @property
    def name(self) -> str:
        return "cancel_scheduled_task"

    @property
    def description(self) -> str:
        return "Cancel a scheduled task by its task ID. Use list_scheduled_tasks first to get task IDs."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to cancel (obtained from list_scheduled_tasks)"
                },
            },
            "required": ["task_id"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        from components.tools.planner.scheduler import TaskScheduler

        task_id = arguments.get("task_id", "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}

        scheduler = TaskScheduler.get_instance()
        task = scheduler.store.get_task(task_id)

        if not task:
            return {"success": False, "error": f"未找到任务 {task_id}"}

        if task.status != "active":
            return {"success": False, "error": f"任务 {task_id} 状态为 {task.status}，无法取消"}

        success = scheduler.store.cancel_task(task_id)
        if success:
            return {
                "success": True,
                "task_id": task_id,
                "message": f"已取消定时任务: {task.description[:100]}",
            }
        return {"success": False, "error": f"取消任务 {task_id} 失败"}
