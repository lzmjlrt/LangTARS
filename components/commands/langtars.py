# LangTARS Command Handler
# Handle direct commands like /shell, /ps, /ls, etc.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncGenerator

from langbot_plugin.api.definition.components.command.command import Command, Subcommand
from langbot_plugin.api.entities.builtin.command.context import ExecuteContext, CommandReturn
from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
from components.helpers.plugin import get_helper

logger = logging.getLogger(__name__)


class BackgroundTaskManager:
    """Background task manager for running auto tasks without blocking command handler."""

    _current_task: asyncio.Task | None = None
    _current_generator: AsyncGenerator | None = None
    _plugin_ref: Any = None
    _result_callback: Any = None
    _bg_task: asyncio.Task | None = None
    _task_running: bool = False
    _last_result: str | None = None
    _pending_result: str | None = None
    
    # Task status tracking
    _current_task_description: str = ""  # Current task description
    _current_step: str = ""  # Current step description (what the agent is doing)
    _current_tool: str = ""  # Current tool being executed
    _task_start_time: float = 0.0  # Task start timestamp
    _llm_call_count: int = 0  # Number of LLM calls made
    
    # Confirmation state for dangerous operations
    _pending_confirmation: dict | None = None  # Pending confirmation request
    _confirmation_callback: asyncio.Future | None = None  # Future to wait for user confirmation
    
    # Message sending context for confirmation notifications
    _bot_uuid: str | None = None
    _target_type: str | None = None
    _target_id: Any = None
    
    # User's new instruction when denying confirmation
    _user_new_instruction: str | None = None
    
    # Generic interactive Q&A state (non-danger confirmation)
    _pending_question: dict | None = None
    _question_callback: asyncio.Future | None = None
    
    # Message history for continue functionality - per user
    # Key: user_id (str), Value: dict with messages, task, registry, llm_model_uuid
    _user_conversation_states: dict[str, dict] = {}
    _current_user_id: str | None = None  # Current user ID for the running task

    @classmethod
    def is_running(cls) -> bool:
        """Check if a background task is running."""
        return cls._task_running and cls._bg_task is not None and not cls._bg_task.done()

    @classmethod
    def get_last_result(cls) -> str | None:
        """Get the last result from the background task."""
        return cls._last_result

    @classmethod
    def get_pending_result(cls) -> str | None:
        """Get pending result that failed to push to chat."""
        return cls._pending_result

    @classmethod
    async def stop(cls) -> bool:
        """Stop the current background task."""
        from components.tools.planner import TrueSubprocessPlanner

        # First try to kill the subprocess
        if TrueSubprocessPlanner.is_running():
            await TrueSubprocessPlanner.kill_process()

        # Then cancel the background task if exists
        if cls._bg_task and not cls._bg_task.done():
            cls._bg_task.cancel()
            try:
                await cls._bg_task
            except asyncio.CancelledError:
                pass

        cls._bg_task = None
        cls._task_running = False
        return True

    @classmethod
    def set_task_status(cls, task_description: str = "", step: str = "", tool: str = "") -> None:
        """Update the current task status."""
        cls._current_task_description = task_description
        cls._current_step = step
        cls._current_tool = tool
        if cls._task_start_time == 0.0:
            cls._task_start_time = time.time()

    @classmethod
    def get_task_status(cls) -> dict:
        """Get the current task status."""
        elapsed = 0.0
        if cls._task_start_time > 0.0:
            elapsed = time.time() - cls._task_start_time
        
        # Get LLM call count from StateManager (the real source)
        llm_call_count = cls._llm_call_count
        try:
            from components.tools.planner.state import get_state_manager
            state_manager = get_state_manager()
            real_count = state_manager.get_llm_call_count()
            if real_count > 0:
                llm_call_count = real_count
        except Exception:
            pass
        
        return {
            "is_running": cls.is_running(),
            "task_description": cls._current_task_description,
            "current_step": cls._current_step,
            "current_tool": cls._current_tool,
            "llm_call_count": llm_call_count,
            "elapsed_seconds": round(elapsed, 1)
        }

    @classmethod
    def increment_llm_call(cls) -> None:
        """Increment the LLM call count."""
        cls._llm_call_count += 1

    @classmethod
    def reset_task_status(cls) -> None:
        """Reset task status for a new task."""
        cls._current_task_description = ""
        cls._current_step = ""
        cls._current_tool = ""
        cls._task_start_time = 0.0
        cls._llm_call_count = 0
        cls._pending_confirmation = None
        cls._confirmation_callback = None
        cls._pending_question = None
        cls._question_callback = None
        # Note: We don't reset conversation states here
        # because they are needed for the continue functionality

    @classmethod
    def set_current_user(cls, user_id: str) -> None:
        """Set the current user ID for the running task."""
        cls._current_user_id = user_id

    @classmethod
    def get_current_user(cls) -> str | None:
        """Get the current user ID."""
        return cls._current_user_id

    @classmethod
    def save_conversation_state(
        cls,
        messages: list,
        task: str,
        registry: Any,
        llm_model_uuid: str,
        user_id: str | None = None
    ) -> None:
        """Save conversation state for continue functionality.
        
        Args:
            messages: The conversation messages
            task: The task description
            registry: The tool registry
            llm_model_uuid: The LLM model UUID
            user_id: The user ID (uses current user if not provided)
        """
        uid = user_id or cls._current_user_id
        if not uid:
            logger.warning("Cannot save conversation state: no user ID")
            return
        
        cls._user_conversation_states[uid] = {
            "messages": messages.copy() if messages else None,
            "task": task,
            "registry": registry,
            "llm_model_uuid": llm_model_uuid
        }

    @classmethod
    def get_conversation_state(cls, user_id: str | None = None) -> tuple[list | None, str | None, Any, str | None]:
        """Get saved conversation state for continue functionality.
        
        Args:
            user_id: The user ID (uses current user if not provided)
        
        Returns:
            Tuple of (messages, task, registry, llm_model_uuid)
        """
        uid = user_id or cls._current_user_id
        if not uid or uid not in cls._user_conversation_states:
            return (None, None, None, None)
        
        state = cls._user_conversation_states[uid]
        return (
            state.get("messages"),
            state.get("task"),
            state.get("registry"),
            state.get("llm_model_uuid")
        )

    @classmethod
    def has_conversation_state(cls, user_id: str | None = None) -> bool:
        """Check if there's a saved conversation state for the user.
        
        Args:
            user_id: The user ID (uses current user if not provided)
        """
        uid = user_id or cls._current_user_id
        if not uid or uid not in cls._user_conversation_states:
            return False
        
        state = cls._user_conversation_states[uid]
        messages = state.get("messages")
        return messages is not None and len(messages) > 0

    @classmethod
    def clear_conversation_state(cls, user_id: str | None = None) -> None:
        """Clear saved conversation state for a user.
        
        Args:
            user_id: The user ID (uses current user if not provided)
        """
        uid = user_id or cls._current_user_id
        if uid and uid in cls._user_conversation_states:
            del cls._user_conversation_states[uid]

    @classmethod
    def clear_all_conversation_states(cls) -> None:
        """Clear all saved conversation states for all users."""
        cls._user_conversation_states.clear()

    @classmethod
    def request_confirmation(cls, tool_name: str, arguments: dict, message: str) -> asyncio.Future:
        """Request confirmation from user for a dangerous operation.
        
        Returns a Future that will be resolved when user confirms or denies.
        """
        cls._pending_confirmation = {
            "tool_name": tool_name,
            "arguments": arguments,
            "message": message,
        }
        cls._confirmation_callback = asyncio.Future()
        return cls._confirmation_callback

    @classmethod
    def confirm(cls, confirmed: bool) -> None:
        """Process user confirmation response."""
        if cls._confirmation_callback and not cls._confirmation_callback.done():
            cls._confirmation_callback.set_result(confirmed)
        cls._pending_confirmation = None

    @classmethod
    def get_pending_confirmation(cls) -> dict | None:
        """Get pending confirmation if any."""
        return cls._pending_confirmation

    @classmethod
    def has_pending_confirmation(cls) -> bool:
        """Check if there's a pending confirmation."""
        return cls._pending_confirmation is not None

    @classmethod
    def set_user_new_instruction(cls, instruction: str) -> None:
        """Set user's new instruction when denying confirmation."""
        cls._user_new_instruction = instruction
        # Also mark as denied to stop the current operation
        cls.confirm(False)

    @classmethod
    def get_user_new_instruction(cls) -> str | None:
        """Get user's new instruction."""
        return cls._user_new_instruction

    @classmethod
    def clear_user_new_instruction(cls) -> None:
        """Clear user's new instruction."""
        cls._user_new_instruction = None

    @classmethod
    def request_user_input(cls, question: str, options: list[str] | None = None, message: str = "") -> asyncio.Future:
        """Request generic user input and return a future resolved by `!tars <answer>`."""
        cls._pending_question = {
            "question": question,
            "options": options or [],
            "message": message,
        }
        cls._question_callback = asyncio.Future()
        return cls._question_callback

    @classmethod
    def submit_user_input(cls, answer: str) -> bool:
        """Submit answer for pending generic user question."""
        if cls._question_callback and not cls._question_callback.done():
            cls._question_callback.set_result(answer)
            cls._pending_question = None
            return True
        return False

    @classmethod
    def clear_pending_user_input(cls) -> None:
        """Clear pending user question state."""
        if cls._question_callback and not cls._question_callback.done():
            cls._question_callback.cancel()
        cls._question_callback = None
        cls._pending_question = None

    @classmethod
    def get_pending_user_question(cls) -> dict | None:
        """Get pending generic user question."""
        return cls._pending_question

    @classmethod
    def has_pending_user_question(cls) -> bool:
        """Check if there's a pending generic user question."""
        return cls._pending_question is not None

    @classmethod
    def set_message_context(cls, bot_uuid: str, target_type: str, target_id: Any) -> None:
        """Set the message sending context for confirmation notifications."""
        cls._bot_uuid = bot_uuid
        cls._target_type = target_type
        cls._target_id = target_id

    @classmethod
    async def send_confirmation_message(cls, message: str, plugin: Any) -> bool:
        """Send a message to the user using the stored context."""
        if not cls._bot_uuid or not cls._target_type or cls._target_id is None:
            return False
        
        try:
            from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
            await plugin.send_message(
                bot_uuid=cls._bot_uuid,
                target_type=cls._target_type,
                target_id=cls._target_id,
                message_chain=MessageChain([Plain(text=message)]),
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to send confirmation message: {e}")
            return False

    @classmethod
    async def cancel_task(cls) -> None:
        """Cancel the running task and stop execution."""
        # Stop the background task
        await cls.stop()
        # Clear confirmation state
        cls.confirm(False)
        # Clear generic question state
        cls.clear_pending_user_input()


class LangTARS(Command):
    """LangTARS Command Handler"""

    async def initialize(self):
        await super().initialize()

        # Register subcommands - only essential commands for AI-powered task execution
        self.registered_subcommands["stop"] = Subcommand(
            subcommand=LanTARSCommand.stop,
            help="Stop the current running task",
            usage="!tars stop",
            aliases=["pause", "停止"],
        )

        self.registered_subcommands["what"] = Subcommand(
            subcommand=LanTARSCommand.what,
            help="What is the agent doing now",
            usage="!tars what",
            aliases=["状态", "进度"],
        )

        self.registered_subcommands["yes"] = Subcommand(
            subcommand=LanTARSCommand.confirm,
            help="Confirm dangerous operation",
            usage="!tars yes",
            aliases=["y", "confirm", "ok", "同意", "好", "确认"],
        )

        self.registered_subcommands["no"] = Subcommand(
            subcommand=LanTARSCommand.deny,
            help="Deny and cancel dangerous operation",
            usage="!tars no",
            aliases=["n", "cancel", "deny", "不同意", "不", "取消"],
        )

        self.registered_subcommands["help"] = Subcommand(
            subcommand=LanTARSCommand.help,
            help="Show command help",
            usage="!tars help",
            aliases=["h", "?", "帮助"],
        )

        self.registered_subcommands["reset"] = Subcommand(
            subcommand=LanTARSCommand.reset,
            help="Reset conversation history to start fresh",
            usage="!tars reset",
            aliases=["清空", "重置", "clear"],
        )

        # Wildcard subcommand to handle task execution (both new and continue)
        self.registered_subcommands["*"] = Subcommand(
            subcommand=LanTARSCommand.default,
            help="Execute a task (new or continue from previous)",
            usage="!tars <task description>",
            aliases=[],
        )

    async def _execute(self, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Inject pending auto-task result before executing next !tars command."""
        # Check user permission
        try:
            user_id = str(context.session.launcher_id) if context.session else None
            if user_id and hasattr(self.plugin, 'is_user_allowed'):
                if not self.plugin.is_user_allowed(user_id):
                    yield CommandReturn(text="⛔ 您没有权限使用此命令。请联系管理员将您添加到允许用户列表中。")
                    return
        except Exception as e:
            logger.warning(f"Failed to check user permission: {e}")
        
        next_cmd = context.crt_params[0] if context.crt_params else ""
        if next_cmd != "result":
            pending = BackgroundTaskManager.get_pending_result()
            if pending:
                BackgroundTaskManager._pending_result = None
                yield CommandReturn(text=f"📬 Last task result (auto):\n\n{pending}")
        async for return_value in super()._execute(context):
            yield return_value


# Separate class for command handlers - uses singleton PluginHelper
class LanTARSCommand:
    """Static command handlers that delegate to shared PluginHelper."""

    @staticmethod
    def _help_text() -> str:
        return """LangTARS - AI 自主任务助手

使用方法:
  !tars <任务描述>          - AI 自主执行任务
                            如果有上次任务的对话历史，会自动继续

控制命令:
  !tars stop               - 停止当前任务
  !tars what               - 查看当前进度/是否在等待确认
  !tars reset              - 清空对话历史，开始全新任务

交互命令:
  !tars yes                - 确认危险操作
  !tars no                 - 取消危险操作并停止任务
  !tars <你的回答>          - 回答插件提出的问题

示例:
  !tars 打开浏览器访问 github.com
  !tars 帮我整理桌面上的文件
  !tars 把刚才的结果保存到文件（基于上次任务继续）
  !tars reset              （清空历史后开始新任务）
"""

    @staticmethod
    async def stop(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle task stopping."""
        import logging
        logger = logging.getLogger(__name__)

        from components.tools.planner import PlannerTool, TrueSubprocessPlanner, SubprocessPlanner

        async def _cleanup_browser() -> None:
            """Best-effort cleanup for Playwright browser resources."""
            try:
                result = await _self_cmd.plugin.browser_cleanup()
                if isinstance(result, dict) and not result.get("success", True):
                    logger.warning(f"[STOP] Browser cleanup reported failure: {result}")
            except Exception as e:
                logger.warning(f"[STOP] Browser cleanup failed: {e}")

        logger.warning(f"[STOP] is_running check: process={TrueSubprocessPlanner._process}, pid={TrueSubprocessPlanner._pid}")

        # Check if background task is running
        if BackgroundTaskManager.is_running():
            logger.warning("[STOP] Background task running, stopping...")
            await BackgroundTaskManager.stop()
            await _cleanup_browser()
            last_result = BackgroundTaskManager.get_last_result()
            if last_result:
                yield CommandReturn(text=f"🛑 Task stopped.\n\nLast output:\n{last_result}")
            else:
                yield CommandReturn(text="🛑 Task has been stopped.")
            return

        # First, try to kill the subprocess directly
        if TrueSubprocessPlanner.is_running():
            logger.warning("[STOP] Subprocess running, killing...")
            await TrueSubprocessPlanner.kill_process()
            await _cleanup_browser()
            yield CommandReturn(text="🛑 Task has been stopped (subprocess killed).")
            return

        # Fallback: set stop flag and remove run file
        logger.warning("[STOP] No subprocess running, using fallback")
        # Only call stop_task if there's actually a task to stop
        # This prevents setting stop flags when no task is running
        from components.tools.planner.state import get_state_manager
        state_manager = get_state_manager()
        if state_manager.current_task:
            PlannerTool.stop_task()
        SubprocessPlanner.remove_run_file()
        await _cleanup_browser()

        yield CommandReturn(text="🛑 Stop signal sent.\n\nIf the task doesn't stop, run in terminal:\n  touch /tmp/langtars_user_stop")

    @staticmethod
    async def what(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Get current task status - what is the agent doing now."""
        status = BackgroundTaskManager.get_task_status()
        if BackgroundTaskManager.has_pending_user_question():
            pending_q = BackgroundTaskManager.get_pending_user_question() or {}
            msg = "🤔 插件正在等你回答:\n\n"
            msg += f"问题: {pending_q.get('question', '')}\n"
            options = pending_q.get("options", []) or []
            if options:
                msg += "可选项: " + " / ".join(str(x) for x in options) + "\n"
            msg += "\n请回复: !tars <你的回答>"
            yield CommandReturn(text=msg)
            return
        
        # Check if there's a pending confirmation
        if BackgroundTaskManager.has_pending_confirmation():
            pending = BackgroundTaskManager.get_pending_confirmation()
            confirm_msg = f"⚠️ 待确认的危险操作:\n\n"
            confirm_msg += f"工具: {pending.get('tool_name', '')}\n"
            args = pending.get('arguments', {})
            if pending.get('tool_name') == 'shell':
                confirm_msg += f"命令: {args.get('command', '')}\n"
            elif pending.get('tool_name') == 'kill_process':
                confirm_msg += f"目标: {args.get('target', '')}\n"
            elif pending.get('tool_name') == 'delete_file':
                confirm_msg += f"文件: {args.get('path', '')}\n"
            confirm_msg += "\n请回复「!tars yes」确认执行，回复!tars no」取消，回复「!tars other」执行新命令。"
            yield CommandReturn(text=confirm_msg)
            return
        
        if not status["is_running"]:
            yield CommandReturn(text="🤖 当前没有正在运行的任务。")
            return

        # Build status message
        msg_parts = []
        msg_parts.append(f"🧠 任务: {status['task_description']}")
        
        if status["current_step"]:
            msg_parts.append(f"📍 进度: {status['current_step']}")
        
        if status["current_tool"]:
            msg_parts.append(f"🔧 工具: {status['current_tool']}")
        
        msg_parts.append(f"📊 LLM调用: {status['llm_call_count']} 次")
        msg_parts.append(f"⏱️ 运行时间: {status['elapsed_seconds']} 秒")
        
        # Add plan display if available
        try:
            from components.tools.planner.state import get_state_manager
            state_manager = get_state_manager()
            if state_manager.has_plan():
                plan_display = state_manager.get_plan_display()
                if plan_display:
                    msg_parts.append("")  # Empty line
                    msg_parts.append(plan_display)
        except Exception as e:
            logger.debug(f"Failed to get plan display: {e}")

        yield CommandReturn(text="\n".join(msg_parts))

    @staticmethod
    async def confirm(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle user confirmation for dangerous operations."""
        params = context.crt_params
        user_input = " ".join(params).lower().strip() if params else ""
        
        # Check if there's a pending confirmation
        if not BackgroundTaskManager.has_pending_confirmation():
            yield CommandReturn(text="ℹ️ 当前没有待确认的危险操作。")
            return
        
        # Check if user confirmed (yes, y, ok, confirm, 可以, 好, 确认, 同意, yes!, ok!)
        confirm_keywords = ["yes", "y", "ok", "confirm", "可以", "好", "确认", "同意", "sure", "yes!", "ok!", "y!", "确认！", "好！", "同意！", "可以！"]
        
        if user_input in confirm_keywords or not user_input:
            # User confirmed
            BackgroundTaskManager.confirm(True)
            yield CommandReturn(text="✅ 已确认，继续执行危险操作...")
        else:
            # User denied
            BackgroundTaskManager.confirm(False)
            yield CommandReturn(text="❌ 已取消危险操作。")

    @staticmethod
    async def deny(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle user denial for dangerous operations - cancel and stop the task."""
        # Check if there's a pending confirmation
        if not BackgroundTaskManager.has_pending_confirmation():
            yield CommandReturn(text="ℹ️ 当前没有待确认的危险操作。")
            return
        
        # Cancel the task and stop execution
        await BackgroundTaskManager.cancel_task()
        yield CommandReturn(text="❌ 已取消并停止任务执行。")

    @staticmethod
    async def other(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle user providing a new instruction - can interrupt running task or replace pending confirmation."""
        from components.tools.planner import TrueSubprocessPlanner
        
        params = context.crt_params
        
        if not params:
            yield CommandReturn(text="请提供新的指令。例如：!tars other 我要查天气")
            return
        
        # Get the new instruction from params
        new_instruction = " ".join(params)
        
        # Check if there's a pending confirmation - handle it
        if BackgroundTaskManager.has_pending_confirmation():
            # Set the new instruction and cancel confirmation
            BackgroundTaskManager.set_user_new_instruction(new_instruction)
            yield CommandReturn(text=f"✅ 已收到新指令：{new_instruction}\n\n正在停止当前任务并开始新任务...")
            return
        
        # Check if there's a running task - stop it and start new one
        if BackgroundTaskManager.is_running() or TrueSubprocessPlanner.is_running():
            # Stop the current task
            await BackgroundTaskManager.stop()
            
            # Store the new instruction for later execution
            BackgroundTaskManager.set_user_new_instruction(new_instruction)
            
            yield CommandReturn(text=f"✅ 已停止当前任务，收到新指令：{new_instruction}\n\n请使用 !tars {new_instruction} 来执行新任务。")
            return
        
        # No task running, just inform user to use !tars
        yield CommandReturn(text=f"ℹ️ 当前没有正在执行的任务。\n\n请使用 !tars {new_instruction} 来执行任务。")

    @staticmethod
    async def default(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle default case: execute task (new or continue), answer pending question, or show help."""
        task = " ".join(context.crt_params).strip() if context.crt_params else ""

        # Handle pending user question
        if BackgroundTaskManager.has_pending_user_question():
            if not task:
                pending_q = BackgroundTaskManager.get_pending_user_question() or {}
                msg = "🤔 插件正在等你回答:\n\n"
                msg += f"问题: {pending_q.get('question', '')}\n"
                options = pending_q.get("options", []) or []
                if options:
                    msg += "可选项: " + " / ".join(str(x) for x in options) + "\n"
                msg += "\n请回复: !tars <你的回答>"
                yield CommandReturn(text=msg)
                return

            if BackgroundTaskManager.submit_user_input(task):
                yield CommandReturn(text=f"✅ 已收到你的回答：{task}")
            else:
                yield CommandReturn(text="⚠️ 当前没有可接收回答的问题。")
            return

        # No task provided - show help
        if not task:
            yield CommandReturn(text=LanTARSCommand._help_text())
            return

        # Check if a task is already running
        from components.tools.planner import PlannerTool, TrueSubprocessPlanner, PlannerExecutor, SubprocessPlanner

        if BackgroundTaskManager.is_running() or TrueSubprocessPlanner.is_running():
            yield CommandReturn(text="⚠️ 任务正在运行中。使用 !tars stop 停止当前任务。")
            return

        # Get user ID and set as current user
        user_id = str(context.session.launcher_id) if context.session else None
        if user_id:
            BackgroundTaskManager.set_current_user(user_id)

        # Determine if this is a continue task or new task
        has_history = BackgroundTaskManager.has_conversation_state(user_id)
        
        # Get config from the command's plugin instance
        config = _self_cmd.plugin.get_config()
        max_iterations = int(config.get("planner_max_iterations", 5) or 5)
        configured_model_uuid = config.get("planner_model_uuid", "")

        # Get available models
        try:
            models = await _self_cmd.plugin.get_llm_models()
            if not models:
                yield CommandReturn(text="""Error: No LLM models available.

Please configure an LLM model in the pipeline settings first.
Go to Pipelines → Configure → Select LLM Model
""")
                return

            if configured_model_uuid:
                for model in models:
                    if isinstance(model, dict) and model.get("uuid") == configured_model_uuid:
                        llm_model_uuid = configured_model_uuid
                        break
                else:
                    first_model = models[0]
                    llm_model_uuid = first_model.get("uuid", "") if isinstance(first_model, dict) else first_model
            else:
                first_model = models[0]
                if isinstance(first_model, dict):
                    llm_model_uuid = first_model.get("uuid", "")
                else:
                    llm_model_uuid = first_model

            if not llm_model_uuid:
                yield CommandReturn(text="Error: Model does not have a valid UUID")
                return
        except Exception as e:
            yield CommandReturn(text=f"Error: Failed to get available models: {str(e)}")
            return

        # Always reset state before starting a new task
        PlannerTool.reset_task_state()
        
        # Initialize background task status
        BackgroundTaskManager.reset_task_status()
        task_type = "继续" if has_history else "新任务"
        BackgroundTaskManager.set_task_status(
            task_description=f"{task_type}: {task}",
            step="任务已启动，正在初始化...",
            tool=""
        )
        BackgroundTaskManager._task_running = True

        # Store current user ID for scheduler tools
        BackgroundTaskManager._current_user_id = user_id

        # Set message context for confirmation notifications
        try:
            bot_uuid_ctx = None
            try:
                bot_uuid_ctx = await context.get_bot_uuid()
            except Exception:
                pass
            if not bot_uuid_ctx:
                conversation = getattr(context.session, "using_conversation", None)
                if conversation and getattr(conversation, "bot_uuid", None):
                    bot_uuid_ctx = str(conversation.bot_uuid)
            if bot_uuid_ctx:
                BackgroundTaskManager.set_message_context(
                    bot_uuid=bot_uuid_ctx,
                    target_type=context.session.launcher_type.value,
                    target_id=context.session.launcher_id
                )
        except Exception as e:
            logger.warning(f"Failed to set message context: {e}")

        # Lazy-start the task scheduler (runs once, subsequent calls are no-op)
        try:
            from components.tools.planner.scheduler import TaskScheduler
            _scheduler = TaskScheduler.get_instance()
            if not _scheduler._running:
                await _scheduler.start(_self_cmd.plugin)
        except Exception as e:
            logger.warning(f"Failed to start task scheduler: {e}")

        # Send task start notification to user
        try:
            bot_uuid_notify: str | None = None
            try:
                bot_uuid_notify = await context.get_bot_uuid()
            except Exception:
                pass
            if not bot_uuid_notify:
                conversation = getattr(context.session, "using_conversation", None)
                if conversation and getattr(conversation, "bot_uuid", None):
                    bot_uuid_notify = str(conversation.bot_uuid)
            
            if bot_uuid_notify:
                notify_target_type = context.session.launcher_type.value
                notify_target_id = context.session.launcher_id
                if has_history:
                    last_task = BackgroundTaskManager.get_conversation_state(user_id)[1]
                    start_msg = f"🔄 继续任务！\n\n新指令: {task[:100]}{'...' if len(task) > 100 else ''}\n基于上次: {last_task[:50] if last_task else '未知'}...\n\n使用 !tars what 查看进度"
                else:
                    start_msg = f"🚀 任务已启动！\n\n任务: {task[:100]}{'...' if len(task) > 100 else ''}\n\n使用 !tars what 查看进度"
                await _self_cmd.plugin.send_message(
                    bot_uuid=bot_uuid_notify,
                    target_type=notify_target_type,
                    target_id=notify_target_id,
                    message_chain=MessageChain([Plain(text=start_msg)]),
                )
        except Exception as e:
            logger.warning(f"Failed to send task start notification: {e}")

        # Start task in background
        try:
            bot_uuid: str | None = None
            try:
                bot_uuid = await context.get_bot_uuid()
                logger.info(f"[DEFAULT] Got bot_uuid from context: {bot_uuid}")
            except Exception as e:
                logger.warning(f"Failed to get bot uuid for background send: {e}")
            if not bot_uuid:
                try:
                    conversation = getattr(context.session, "using_conversation", None)
                    if conversation and getattr(conversation, "bot_uuid", None):
                        bot_uuid = str(conversation.bot_uuid)
                        logger.info(f"[DEFAULT] Got bot_uuid from conversation: {bot_uuid}")
                except Exception:
                    pass
            target_type = context.session.launcher_type.value
            raw_target_id = context.session.launcher_id
            logger.info(f"[DEFAULT] target_type={target_type}, raw_target_id={raw_target_id}, bot_uuid={bot_uuid}")

            def _candidate_target_ids(raw_id: Any) -> list[Any]:
                ids: list[Any] = []
                if raw_id is None:
                    return ids
                ids.append(raw_id)
                sid = str(raw_id)
                if sid not in [str(x) for x in ids]:
                    ids.append(sid)
                if sid.isdigit():
                    try:
                        iid = int(sid)
                        if str(iid) not in [str(x) for x in ids]:
                            ids.append(iid)
                    except Exception:
                        pass
                return ids

            async def _reply_background(text: str) -> None:
                """Queue task result for auto-show on next !tars command."""
                try:
                    if not text:
                        return
                    safe_text = text if len(text) <= 3000 else ("...(truncated)\n" + text[-2800:])
                    BackgroundTaskManager._pending_result = safe_text
                    logger.info("Background task result queued. It will auto-show on next !tars command.")
                except Exception as e:
                    BackgroundTaskManager._pending_result = text if len(text) <= 3000 else ("...(truncated)\n" + text[-2800:])
                    logger.warning(f"Failed to queue background result: {e}")

            async def _auto_execute_result_reply() -> None:
                """Auto-run result behavior when task ends via send_message (query-independent)."""
                logger.info(f"[DEFAULT] _auto_execute_result_reply called, bot_uuid={bot_uuid}, target_type={target_type}, raw_target_id={raw_target_id}")
                pending = BackgroundTaskManager.get_pending_result()
                if pending:
                    msg = f"📬 任务结果:\n\n{pending}"
                else:
                    last = BackgroundTaskManager.get_last_result()
                    if last:
                        msg = f"📄 任务结果:\n\n{last}"
                    else:
                        msg = "任务完成，无结果。"
                logger.info(f"[DEFAULT] Message to send: {msg[:100]}...")
                try:
                    if not bot_uuid:
                        raise RuntimeError("missing bot_uuid")
                    sent = False
                    errors: list[str] = []
                    for cid in _candidate_target_ids(raw_target_id):
                        try:
                            logger.info(f"[DEFAULT] Trying to send to bot_uuid={bot_uuid}, target_type={target_type}, target_id={cid}")
                            await _self_cmd.plugin.send_message(
                                bot_uuid=bot_uuid,
                                target_type=target_type,
                                target_id=cid,
                                message_chain=MessageChain([Plain(text=msg)]),
                            )
                            logger.info(f"Auto result sent via send_message to {target_type}:{cid!r}")
                            sent = True
                            break
                        except Exception as send_err:
                            logger.warning(f"[DEFAULT] send_message failed for {cid}: {send_err}")
                            errors.append(f"{cid!r}: {send_err}")
                    if sent:
                        if pending:
                            BackgroundTaskManager._pending_result = None
                    else:
                        raise RuntimeError(" | ".join(errors) if errors else "unknown send error")
                except Exception as e:
                    logger.warning(f"Auto result send failed, keep pending for next !tars command: {e}")

            async def _cleanup_browser(phase: str) -> None:
                """Best-effort cleanup for Playwright browser resources."""
                try:
                    result = await _self_cmd.plugin.browser_cleanup()
                    if isinstance(result, dict) and not result.get("success", True):
                        logger.warning(f"[DEFAULT] Browser cleanup reported failure ({phase}): {result}")
                except Exception as cleanup_err:
                    logger.warning(f"[DEFAULT] Browser cleanup failed ({phase}): {cleanup_err}")

            async def run_task():
                try:
                    # Keep the run file semantics so stop checks stay consistent
                    SubprocessPlanner.create_run_file()

                    # Initialize tool registry
                    from components.tools.planner_tools.registry import ToolRegistry
                    registry = ToolRegistry(_self_cmd.plugin)
                    await registry.initialize()

                    executor = PlannerExecutor()
                    
                    if has_history:
                        # Continue with existing conversation
                        last_messages, last_task_desc, last_registry, last_llm_uuid = BackgroundTaskManager.get_conversation_state(user_id)
                        
                        # Import necessary modules
                        from langbot_plugin.api.entities.builtin.provider import message as provider_message
                        
                        # Build continuation messages based on saved conversation
                        messages = list(last_messages) if last_messages else []
                        
                        # Add the new instruction as a user message
                        messages.append(provider_message.Message(
                            role="user",
                            content=f"用户继续指令: {task}\n\n请基于之前的对话上下文，继续执行这个新指令。"
                        ))
                        
                        async for partial_result in executor.execute_task_streaming_with_messages(
                            messages=messages,
                            task=f"继续: {task}",
                            original_task=last_task_desc,
                            max_iterations=max_iterations,
                            llm_model_uuid=last_llm_uuid or llm_model_uuid,
                            plugin=_self_cmd.plugin,
                            helper_plugin=_self_cmd.plugin,
                            registry=last_registry or registry,
                            session=context.session,
                            query_id=context.query_id
                        ):
                            BackgroundTaskManager._last_result = partial_result
                            await asyncio.sleep(0.1)
                    else:
                        # New task
                        async for partial_result in executor.execute_task_streaming(
                            task=task,
                            max_iterations=max_iterations,
                            llm_model_uuid=llm_model_uuid,
                            plugin=_self_cmd.plugin,
                            helper_plugin=_self_cmd.plugin,
                            registry=registry,
                            session=context.session,
                            query_id=context.query_id
                        ):
                            BackgroundTaskManager._last_result = partial_result
                            await asyncio.sleep(0.1)
                    
                    if BackgroundTaskManager._last_result:
                        await _reply_background(f"✅ 任务完成。\n\n{BackgroundTaskManager._last_result}")
                    else:
                        await _reply_background("✅ 任务完成。")
                    await _auto_execute_result_reply()
                except asyncio.CancelledError:
                    BackgroundTaskManager._last_result = "任务被用户取消。"
                    await _reply_background("🛑 任务被用户取消。")
                    await _auto_execute_result_reply()
                    raise
                except Exception as e:
                    import traceback
                    BackgroundTaskManager._last_result = f"Error: {str(e)}\n{traceback.format_exc()}"
                    await _reply_background(f"❌ 任务错误:\n{BackgroundTaskManager._last_result}")
                    await _auto_execute_result_reply()
                finally:
                    SubprocessPlanner.remove_run_file()
                    if bool(config.get("auto_cleanup_browser_on_finish", False)):
                        await _cleanup_browser("run_task.finally")
                    BackgroundTaskManager._task_running = False
                    BackgroundTaskManager._current_step = "任务已完成"

            BackgroundTaskManager._last_result = None
            BackgroundTaskManager._pending_result = None
            bg_task = asyncio.create_task(run_task())
            BackgroundTaskManager._task_running = True
            BackgroundTaskManager._bg_task = bg_task

            if has_history:
                yield CommandReturn(text=f"🔄 继续任务已启动！基于上次对话继续执行。使用 !tars stop 取消。\n")
            else:
                yield CommandReturn(text=f"🚀 任务已启动！使用 !tars stop 取消。\n")

        except Exception as e:
            import traceback
            yield CommandReturn(text=f"Error starting task: {str(e)}\n\n{traceback.format_exc()}")

    @staticmethod
    async def help(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Show explicit help command."""
        yield CommandReturn(text=LanTARSCommand._help_text())

    @staticmethod
    async def reset(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Reset conversation history to start fresh."""
        # Get user ID from context
        user_id = str(context.session.launcher_id) if context.session else None
        
        if not user_id:
            yield CommandReturn(text="⚠️ 无法获取用户ID，无法重置对话历史。")
            return
        
        # Check if there's a conversation state to clear
        if BackgroundTaskManager.has_conversation_state(user_id):
            BackgroundTaskManager.clear_conversation_state(user_id)
            yield CommandReturn(text="✅ 对话历史已清空！下次使用 !tars 将开始全新的任务。")
        else:
            yield CommandReturn(text="ℹ️ 当前没有保存的对话历史。")

    # Legacy code below - keeping for reference but not used
    @staticmethod
    async def _legacy_continue(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Continue with a new instruction based on the last completed task's conversation."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="""Usage: !tars continue <new instruction>

此命令允许你基于上次任务的对话历史继续执行新指令。
AI 会记住之前的上下文，可以更好地理解你的新需求。

Example:
  !tars continue 把刚才的结果保存到文件
  !tars continue 再帮我搜索一下相关的内容
""")
            return

        # Check if there's a saved conversation state
        if not BackgroundTaskManager.has_conversation_state():
            yield CommandReturn(text="⚠️ 没有可继续的对话历史。请先使用 !tars auto <任务> 执行一个任务。")
            return

        # Check if a task is already running
        from components.tools.planner import PlannerTool, TrueSubprocessPlanner, PlannerExecutor, SubprocessPlanner

        if BackgroundTaskManager.is_running() or TrueSubprocessPlanner.is_running():
            yield CommandReturn(text="⚠️ A task is already running. Use !tars stop to stop it first.")
            return

        new_instruction = " ".join(params)

        # Get saved conversation state
        last_messages, last_task, last_registry, last_llm_model_uuid = BackgroundTaskManager.get_conversation_state()

        if not last_messages or not last_llm_model_uuid:
            yield CommandReturn(text="⚠️ 对话历史不完整，无法继续。请使用 !tars auto <任务> 开始新任务。")
            return

        # Get config from the command's plugin instance
        config = _self_cmd.plugin.get_config()
        max_iterations = int(config.get("planner_max_iterations", 5) or 5)

        # Use the saved LLM model UUID
        llm_model_uuid = last_llm_model_uuid

        # Always reset state before starting a new task
        PlannerTool.reset_task_state()
        
        # Initialize background task status
        BackgroundTaskManager.reset_task_status()
        BackgroundTaskManager.set_task_status(
            task_description=f"继续: {new_instruction}",
            step="任务已启动，正在初始化...",
            tool=""
        )
        BackgroundTaskManager._task_running = True
        
        # Set message context for confirmation notifications
        try:
            bot_uuid_ctx = None
            try:
                bot_uuid_ctx = await context.get_bot_uuid()
            except Exception:
                pass
            if not bot_uuid_ctx:
                conversation = getattr(context.session, "using_conversation", None)
                if conversation and getattr(conversation, "bot_uuid", None):
                    bot_uuid_ctx = str(conversation.bot_uuid)
            if bot_uuid_ctx:
                BackgroundTaskManager.set_message_context(
                    bot_uuid=bot_uuid_ctx,
                    target_type=context.session.launcher_type.value,
                    target_id=context.session.launcher_id
                )
        except Exception as e:
            logger.warning(f"Failed to set message context: {e}")

        # Send task start notification to user
        try:
            bot_uuid_notify: str | None = None
            try:
                bot_uuid_notify = await context.get_bot_uuid()
            except Exception:
                pass
            if not bot_uuid_notify:
                conversation = getattr(context.session, "using_conversation", None)
                if conversation and getattr(conversation, "bot_uuid", None):
                    bot_uuid_notify = str(conversation.bot_uuid)
            
            if bot_uuid_notify:
                notify_target_type = context.session.launcher_type.value
                notify_target_id = context.session.launcher_id
                start_msg = f"🔄 继续任务！\n\n新指令: {new_instruction[:100]}{'...' if len(new_instruction) > 100 else ''}\n基于上次任务: {last_task[:50] if last_task else '未知'}...\n\n使用 !tars what 查看进度"
                await _self_cmd.plugin.send_message(
                    bot_uuid=bot_uuid_notify,
                    target_type=notify_target_type,
                    target_id=notify_target_id,
                    message_chain=MessageChain([Plain(text=start_msg)]),
                )
        except Exception as e:
            logger.warning(f"Failed to send task start notification: {e}")

        # Start task in background
        try:
            bot_uuid: str | None = None
            try:
                bot_uuid = await context.get_bot_uuid()
                logger.info(f"[CONTINUE] Got bot_uuid from context: {bot_uuid}")
            except Exception as e:
                logger.warning(f"Failed to get bot uuid for background send: {e}")
            if not bot_uuid:
                try:
                    conversation = getattr(context.session, "using_conversation", None)
                    if conversation and getattr(conversation, "bot_uuid", None):
                        bot_uuid = str(conversation.bot_uuid)
                        logger.info(f"[CONTINUE] Got bot_uuid from conversation: {bot_uuid}")
                except Exception:
                    pass
            target_type = context.session.launcher_type.value
            raw_target_id = context.session.launcher_id
            logger.info(f"[CONTINUE] target_type={target_type}, raw_target_id={raw_target_id}, bot_uuid={bot_uuid}")

            def _candidate_target_ids(raw_id: Any) -> list[Any]:
                ids: list[Any] = []
                if raw_id is None:
                    return ids
                ids.append(raw_id)
                sid = str(raw_id)
                if sid not in [str(x) for x in ids]:
                    ids.append(sid)
                if sid.isdigit():
                    try:
                        iid = int(sid)
                        if str(iid) not in [str(x) for x in ids]:
                            ids.append(iid)
                    except Exception:
                        pass
                return ids

            async def _reply_background(text: str) -> None:
                """Queue task result for auto-show on next !tars command."""
                try:
                    if not text:
                        return
                    safe_text = text if len(text) <= 3000 else ("...(truncated)\n" + text[-2800:])
                    BackgroundTaskManager._pending_result = safe_text
                    logger.info("Background task result queued. It will auto-show on next !tars command.")
                except Exception as e:
                    BackgroundTaskManager._pending_result = text if len(text) <= 3000 else ("...(truncated)\n" + text[-2800:])
                    logger.warning(f"Failed to queue background result: {e}")

            async def _auto_execute_result_reply() -> None:
                """Auto-run result behavior when task ends via send_message (query-independent)."""
                logger.info(f"[CONTINUE] _auto_execute_result_reply called, bot_uuid={bot_uuid}, target_type={target_type}, raw_target_id={raw_target_id}")
                pending = BackgroundTaskManager.get_pending_result()
                if pending:
                    msg = f"📬 Last task result (fallback):\n\n{pending}"
                else:
                    last = BackgroundTaskManager.get_last_result()
                    if last:
                        msg = f"📄 Last task result:\n\n{last}"
                    else:
                        msg = "No task result found."
                logger.info(f"[CONTINUE] Message to send: {msg[:100]}...")
                try:
                    if not bot_uuid:
                        raise RuntimeError("missing bot_uuid")
                    sent = False
                    errors: list[str] = []
                    for cid in _candidate_target_ids(raw_target_id):
                        try:
                            logger.info(f"[CONTINUE] Trying to send to bot_uuid={bot_uuid}, target_type={target_type}, target_id={cid}")
                            await _self_cmd.plugin.send_message(
                                bot_uuid=bot_uuid,
                                target_type=target_type,
                                target_id=cid,
                                message_chain=MessageChain([Plain(text=msg)]),
                            )
                            logger.info(f"Auto result sent via send_message to {target_type}:{cid!r}")
                            sent = True
                            break
                        except Exception as send_err:
                            logger.warning(f"[CONTINUE] send_message failed for {cid}: {send_err}")
                            errors.append(f"{cid!r}: {send_err}")
                    if sent:
                        if pending:
                            BackgroundTaskManager._pending_result = None
                    else:
                        raise RuntimeError(" | ".join(errors) if errors else "unknown send error")
                except Exception as e:
                    logger.warning(f"Auto result send failed, keep pending for next !tars command: {e}")

            async def _cleanup_browser(phase: str) -> None:
                """Best-effort cleanup for Playwright browser resources."""
                try:
                    result = await _self_cmd.plugin.browser_cleanup()
                    if isinstance(result, dict) and not result.get("success", True):
                        logger.warning(f"[CONTINUE] Browser cleanup reported failure ({phase}): {result}")
                except Exception as cleanup_err:
                    logger.warning(f"[CONTINUE] Browser cleanup failed ({phase}): {cleanup_err}")

            async def run_continue_task():
                try:
                    # Keep the run file semantics so stop checks stay consistent
                    SubprocessPlanner.create_run_file()

                    # Use the saved registry or initialize a new one
                    registry = last_registry
                    if not registry:
                        from components.tools.planner_tools.registry import ToolRegistry
                        registry = ToolRegistry(_self_cmd.plugin)
                        await registry.initialize()

                    # Import necessary modules
                    from langbot_plugin.api.entities.builtin.provider import message as provider_message
                    from components.tools.planner.prompts import PromptManager

                    # Build continuation messages based on saved conversation
                    messages = list(last_messages)  # Copy the saved messages
                    
                    # Add the new instruction as a user message
                    messages.append(provider_message.Message(
                        role="user",
                        content=f"用户继续指令: {new_instruction}\n\n请基于之前的对话上下文，继续执行这个新指令。"
                    ))

                    executor = PlannerExecutor()
                    async for partial_result in executor.execute_task_streaming_with_messages(
                        messages=messages,
                        task=f"继续: {new_instruction}",
                        original_task=last_task,
                        max_iterations=max_iterations,
                        llm_model_uuid=llm_model_uuid,
                        plugin=_self_cmd.plugin,
                        helper_plugin=_self_cmd.plugin,
                        registry=registry,
                        session=context.session,
                        query_id=context.query_id
                    ):
                        # Store latest result for stop command to retrieve
                        BackgroundTaskManager._last_result = partial_result
                        # Small delay to allow stop command to be processed
                        await asyncio.sleep(0.1)
                    if BackgroundTaskManager._last_result:
                        await _reply_background(f"✅ Task completed.\n\n{BackgroundTaskManager._last_result}")
                    else:
                        await _reply_background("✅ Task completed.")
                    await _auto_execute_result_reply()
                except asyncio.CancelledError:
                    BackgroundTaskManager._last_result = "Task cancelled by user."
                    await _reply_background("🛑 Task cancelled by user.")
                    await _auto_execute_result_reply()
                    raise
                except Exception as e:
                    import traceback
                    BackgroundTaskManager._last_result = f"Error: {str(e)}\n{traceback.format_exc()}"
                    await _reply_background(f"❌ Task error:\n{BackgroundTaskManager._last_result}")
                    await _auto_execute_result_reply()
                finally:
                    SubprocessPlanner.remove_run_file()
                    if bool(config.get("auto_cleanup_browser_on_finish", False)):
                        await _cleanup_browser("run_continue_task.finally")
                    BackgroundTaskManager._task_running = False
                    BackgroundTaskManager._current_step = "任务已完成"

            BackgroundTaskManager._last_result = None
            BackgroundTaskManager._pending_result = None
            bg_task = asyncio.create_task(run_continue_task())
            BackgroundTaskManager._task_running = True
            BackgroundTaskManager._bg_task = bg_task

            yield CommandReturn(text=f"🔄 继续任务已启动！基于上次对话继续执行。Use !tars stop to cancel.\n")

        except Exception as e:
            import traceback
            yield CommandReturn(text=f"Error starting continue task: {str(e)}\n\n{traceback.format_exc()}")
