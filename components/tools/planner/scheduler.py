# Task Scheduler Engine - Background asyncio loop for executing scheduled tasks
# Singleton that polls for due tasks and dispatches them

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from .scheduler_store import SchedulerStore, ScheduledTask

logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Singleton scheduler that runs a background asyncio loop.
    Checks for due tasks every POLL_INTERVAL seconds and executes them.

    - reminder tasks: fire-and-forget (concurrent, no state conflict)
    - execute tasks: serialized via _execute_lock because they share
      the global StateManager singleton.
    """

    _instance: 'TaskScheduler | None' = None

    POLL_INTERVAL = 15  # seconds between checks
    MAX_EXECUTE_RETRY_WAIT = 300  # max seconds to wait for user task to finish

    def __init__(self):
        self._running = False
        self._loop_task: asyncio.Task | None = None
        self._plugin: Any = None
        self._store: SchedulerStore | None = None
        self._executing_task_ids: set[str] = set()  # track in-flight tasks
        self._execute_lock = asyncio.Lock()  # serialize execute-type tasks

    @classmethod
    def get_instance(cls) -> 'TaskScheduler':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def store(self) -> SchedulerStore:
        if self._store is None:
            self._store = SchedulerStore()
        return self._store

    async def start(self, plugin: Any) -> None:
        """Start the scheduler loop. Called once during first user interaction."""
        if self._running:
            return
        self._plugin = plugin
        self._store = SchedulerStore()
        self._running = True
        self._loop_task = asyncio.create_task(self._poll_loop())
        logger.info("定时任务调度器已启动")

        # Recover overdue tasks from persistence
        self._recover_overdue_tasks()

    def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        logger.info("定时任务调度器已停止")

    def _recover_overdue_tasks(self) -> None:
        """Check for tasks that were missed during downtime and recompute cron next_run."""
        for task in self.store.get_active_tasks():
            if task.schedule_type == "cron" and task.cron_expr:
                # Recompute next run time from now
                try:
                    from croniter import croniter
                    cron = croniter(task.cron_expr, datetime.now())
                    task.next_run_ts = cron.get_next(float)
                    self.store.update_task(task)
                    logger.info(f"恢复 cron 任务 {task.task_id}, 下次运行: {datetime.fromtimestamp(task.next_run_ts)}")
                except Exception as e:
                    logger.error(f"恢复 cron 任务失败 {task.task_id}: {e}")

        # Cleanup old finished tasks
        removed = self.store.cleanup_old_tasks()
        if removed:
            logger.info(f"清理了 {removed} 个过期任务")

    async def _poll_loop(self) -> None:
        """Main loop: every POLL_INTERVAL seconds, check for due tasks."""
        while self._running:
            try:
                due_tasks = self.store.get_due_tasks()
                for task in due_tasks:
                    # Skip tasks already being executed
                    if task.task_id not in self._executing_task_ids:
                        self._executing_task_ids.add(task.task_id)
                        asyncio.create_task(self._execute_task_wrapper(task))
            except Exception as e:
                logger.error(f"调度器轮询出错: {e}")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def _execute_task_wrapper(self, task: ScheduledTask) -> None:
        """Wrapper that ensures task ID is removed from executing set when done."""
        try:
            await self._execute_task(task)
        finally:
            self._executing_task_ids.discard(task.task_id)

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Execute a single scheduled task."""
        logger.info(f"执行定时任务: {task.task_id} ({task.task_type}: {task.description[:50]})")
        try:
            if task.task_type == "reminder":
                # Reminders are stateless - can run concurrently
                await self._send_reminder(task)
            elif task.task_type == "execute":
                # Execute tasks share the global StateManager - must serialize
                async with self._execute_lock:
                    await self._execute_react_task(task)

            # Update state after successful execution
            task.last_run_ts = time.time()
            task.run_count += 1

            if task.schedule_type == "cron" and task.cron_expr:
                # Compute next run for cron tasks
                try:
                    from croniter import croniter
                    cron = croniter(task.cron_expr, datetime.now())
                    task.next_run_ts = cron.get_next(float)
                    logger.info(f"Cron 任务 {task.task_id} 下次运行: {datetime.fromtimestamp(task.next_run_ts)}")
                except Exception as e:
                    logger.error(f"计算下次 cron 时间失败: {e}")
                    task.status = "failed"
                    task.error_message = f"cron 计算失败: {e}"
            elif task.max_runs > 0 and task.run_count >= task.max_runs:
                task.status = "completed"
            # If max_runs == 0 and not cron, mark completed (shouldn't happen but safe)
            elif task.schedule_type != "cron":
                task.status = "completed"

            self.store.update_task(task)

        except Exception as e:
            logger.error(f"执行定时任务失败 {task.task_id}: {e}")
            task.status = "failed"
            task.error_message = str(e)[:200]
            self.store.update_task(task)

            # Try to notify user of failure
            try:
                await self._send_message(
                    task,
                    f"⚠️ 定时任务执行失败\n任务: {task.description[:100]}\n错误: {str(e)[:200]}"
                )
            except Exception:
                pass

    async def _send_message(self, task: ScheduledTask, text: str) -> None:
        """Send a message using the stored messaging context."""
        if not self._plugin or not task.bot_uuid:
            logger.warning(f"无法发送消息: plugin={bool(self._plugin)}, bot_uuid={task.bot_uuid}")
            return

        from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
        await self._plugin.send_message(
            bot_uuid=task.bot_uuid,
            target_type=task.target_type,
            target_id=task.target_id,
            message_chain=MessageChain([Plain(text=text)]),
        )

    async def _send_reminder(self, task: ScheduledTask) -> None:
        """Send a reminder message."""
        msg = f"⏰ 定时提醒\n\n{task.description}"
        await self._send_message(task, msg)
        logger.info(f"已发送提醒: {task.task_id}")

    async def _execute_react_task(self, task: ScheduledTask) -> None:
        """Execute a task through the full ReAct loop, then send result.

        IMPORTANT: This method MUST be called under self._execute_lock
        because it resets and uses the shared global StateManager singleton.
        """
        from components.commands.langtars import BackgroundTaskManager
        from .tool import PlannerTool
        from .state import get_state_manager
        from main import LangTARS

        # Wait if user is currently running a task (avoid concurrency conflict)
        waited = 0
        while BackgroundTaskManager.is_running() and waited < self.MAX_EXECUTE_RETRY_WAIT:
            await asyncio.sleep(15)
            waited += 15
        if BackgroundTaskManager.is_running():
            logger.warning(f"定时任务 {task.task_id} 跳过执行: 用户任务仍在运行")
            await self._send_message(
                task,
                f"⚠️ 定时任务延迟通知\n\n任务「{task.description[:80]}」因当前有其他任务在执行，已跳过本次。下次将按计划执行。"
            )
            return

        # Reset shared state manager to clear stale stop signals from previous tasks
        state_mgr = get_state_manager()
        state_mgr.reset()
        PlannerTool.reset_task_state()

        # create a run file so that _call_llm_with_stop_check doesn't immediately
        # cancel the LLM call.  Manual tasks already do this in the command
        # handler; scheduled tasks must do the same.
        try:
            state_mgr.create_run_file()
        except Exception as e:
            logger.warning(f"Unable to create run file for scheduled task: {e}")

        planner = PlannerTool()
        config = self._plugin.get_config() if hasattr(self._plugin, 'get_config') else {}

        # Resolve LLM model
        llm_model_uuid = config.get('planner_model_uuid', '')
        if not llm_model_uuid:
            try:
                models = await self._plugin.get_llm_models()
                if models:
                    first = models[0]
                    llm_model_uuid = first.get('uuid', '') if isinstance(first, dict) else first
            except Exception as e:
                logger.error(f"获取 LLM 模型失败: {e}")
                raise

        if not llm_model_uuid:
            raise RuntimeError("没有可用的 LLM 模型")

        # Build helper plugin for tool execution.  We create a fresh
        # LangTARS instance to avoid polluting the primary plugin state,
        # but we still need a reference to the real plugin so that
        # confirmation messages (and other runtime-dependent APIs) work.
        helper = LangTARS()
        helper.config = config.copy()
        await helper.initialize()
        # point helper back to the real plugin instance
        try:
            helper.plugin = self._plugin
            helper._plugin = self._plugin
        except Exception:
            pass

        registry = await planner._get_tool_registry(self._plugin)
        # Exclude scheduler tools to prevent recursive task creation
        SCHEDULER_TOOL_NAMES = {"schedule_task", "list_scheduled_tasks", "cancel_scheduled_task"}
        filtered_registry = registry.create_filtered_copy(SCHEDULER_TOOL_NAMES)
        max_iterations = config.get('planner_max_iterations', 10)

        # Notify user that task is starting
        await self._send_message(
            task,
            f"🤖 开始执行定时任务\n\n任务: {task.description[:200]}"
        )

        try:
            result = await planner.execute_task(
                task=task.description,
                max_iterations=max_iterations,
                llm_model_uuid=llm_model_uuid,
                plugin=self._plugin,
                helper_plugin=helper,
                registry=filtered_registry,
            )

            # Send result back to user
            result_text = result[:2000] if result else "（无返回结果）"
            msg = f"📋 定时任务完成\n\n任务: {task.description[:100]}\n\n结果:\n{result_text}"
            await self._send_message(task, msg)
            logger.info(f"定时任务执行完成: {task.task_id}")
        finally:
            # cleanup run file so subsequent schedules don't cancel immediately
            try:
                state_mgr.remove_run_file()
            except Exception:
                pass
