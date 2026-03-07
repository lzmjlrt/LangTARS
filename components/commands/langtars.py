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
        
        return {
            "is_running": cls.is_running(),
            "task_description": cls._current_task_description,
            "current_step": cls._current_step,
            "current_tool": cls._current_tool,
            "llm_call_count": cls._llm_call_count,
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

        # Register subcommands with class methods (unbound)
        self.registered_subcommands["shell"] = Subcommand(
            subcommand=LanTARSCommand.shell,
            help="Execute a shell command",
            usage="!tars shell <command>",
            aliases=["sh", "exec"],
        )

        self.registered_subcommands["ps"] = Subcommand(
            subcommand=LanTARSCommand.ps,
            help="List running processes",
            usage="!tars ps [filter] [limit]",
            aliases=["processes", "process"],
        )

        self.registered_subcommands["kill"] = Subcommand(
            subcommand=LanTARSCommand.kill,
            help="Kill a process by name or PID",
            usage="!tars kill <name|PID> [-f]",
            aliases=[],
        )

        self.registered_subcommands["ls"] = Subcommand(
            subcommand=LanTARSCommand.ls,
            help="List directory contents",
            usage="!tars ls [path] [-a]",
            aliases=["list", "dir"],
        )

        self.registered_subcommands["cat"] = Subcommand(
            subcommand=LanTARSCommand.cat,
            help="Read file content",
            usage="!tars cat <path>",
            aliases=["read", "view"],
        )

        self.registered_subcommands["write"] = Subcommand(
            subcommand=LanTARSCommand.write,
            help="Write content to a file",
            usage="!tars write <path> <content>",
            aliases=["save", "create"],
        )

        self.registered_subcommands["open"] = Subcommand(
            subcommand=LanTARSCommand.open,
            help="Open an application or URL",
            usage="!tars open <app|url>",
            aliases=["launch", "start"],
        )

        self.registered_subcommands["close"] = Subcommand(
            subcommand=LanTARSCommand.close,
            help="Close an application",
            usage="!tars close <app_name> [-f]",
            aliases=["quit"],
        )

        self.registered_subcommands["stop"] = Subcommand(
            subcommand=LanTARSCommand.stop,
            help="Stop the current running task",
            usage="!tars stop",
            aliases=["pause", "cancel"],
        )

        self.registered_subcommands["logs"] = Subcommand(
            subcommand=LanTARSCommand.logs,
            help="View plugin logs",
            usage="!tars logs [lines]",
            aliases=["log"],
        )
        self.registered_subcommands["result"] = Subcommand(
            subcommand=LanTARSCommand.result,
            help="Get last auto task result",
            usage="!tars result",
            aliases=["last"],
        )

        self.registered_subcommands["what"] = Subcommand(
            subcommand=LanTARSCommand.what,
            help="What is the agent doing now",
            usage="!tars what",
            aliases=[],
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

        self.registered_subcommands["other"] = Subcommand(
            subcommand=LanTARSCommand.other,
            help="Provide new instruction instead of confirming",
            usage="!tars other <new instruction>",
            aliases=["other!", "换个任务", "新任务", "改变任务"],
        )

        self.registered_subcommands["help"] = Subcommand(
            subcommand=LanTARSCommand.help,
            help="Show command help",
            usage="!tars help",
            aliases=["h", "?", "帮助"],
        )

        self.registered_subcommands["top"] = Subcommand(
            subcommand=LanTARSCommand.top,
            help="Show running applications",
            usage="!tars top",
            aliases=["apps"],
        )

        self.registered_subcommands["info"] = Subcommand(
            subcommand=LanTARSCommand.info,
            help="Show system information",
            usage="!tars info",
            aliases=["system", "status"],
        )

        self.registered_subcommands["search"] = Subcommand(
            subcommand=LanTARSCommand.search,
            help="Search for files",
            usage="!tars search <pattern> [path]",
            aliases=["find"],
        )

        self.registered_subcommands["auto"] = Subcommand(
            subcommand=LanTARSCommand.auto,
            help="Autonomous task planning (AI-powered)",
            usage="!tars auto <task description>",
            aliases=["plan", "run"],
        )

        # Wildcard subcommand to handle no subcommand
        self.registered_subcommands["*"] = Subcommand(
            subcommand=LanTARSCommand.default,
            help="Show help or handle default",
            usage="!tars help",
            aliases=[],
        )

    async def _execute(self, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Inject pending auto-task result before executing next !tars command."""
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
        return """LangTARS - 命令大全

核心命令:
  !tars auto <任务>         - AI 自主执行任务
  !tars stop               - 停止当前任务
  !tars what               - 查看当前进度/是否在等待确认
  !tars result             - 查看最近任务结果
  !tars logs [行数]        - 查看日志

交互命令:
  !tars yes                - 确认危险操作
  !tars no                 - 取消危险操作并停止任务
  !tars other <新指令>      - 放弃当前危险操作并改做新任务
  !tars <你的回答>          - 回答插件提出的问题（例如二选一）

系统命令:
  !tars shell <命令>        - 执行 shell 命令
  !tars ps [filter]        - 列进程
  !tars kill <pid|name>    - 结束进程
  !tars ls [path]          - 列目录
  !tars cat <path>         - 读文件
  !tars write <path> <txt> - 写文件
  !tars search <pattern>   - 搜文件
  !tars open <app|url>     - 打开应用或网址
  !tars close <app>        - 关闭应用
  !tars apps               - 列运行中的应用
  !tars info               - 查看系统信息
"""

    @staticmethod
    async def shell(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle shell command execution."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars shell <command>")
            return

        command = " ".join(params)
        yield CommandReturn(text=f"Executing: `{command}`\n\n")

        helper = await get_helper()
        result = await helper.run_shell(command)

        if result["success"]:
            output = result.get("stdout", "") or result.get("stderr", "")
            yield CommandReturn(text=f"Command executed successfully\n\n```\n{output}\n```")
        else:
            yield CommandReturn(text=f"Command failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def ps(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle process listing."""
        params = context.crt_params
        filter_pattern = params[0] if params else None
        limit = 20

        helper = await get_helper()
        result = await helper.list_processes(filter_pattern, limit)

        if result["success"]:
            processes = result.get("processes", [])
            if not processes:
                yield CommandReturn(text="No processes found.")
                return

            lines = ["**Processes:**\n"]
            lines.append(f"{'PID':<8} {'CPU%':<8} {'MEM%':<8} {'COMMAND'}")
            lines.append("-" * 60)
            for p in processes[:15]:
                cmd = p.get("command", "")[:30]
                lines.append(f"{p.get('pid',''):<8} {p.get('cpu',''):<8} {p.get('mem',''):<8} {cmd}")

            if len(processes) > 15:
                lines.append(f"... and {len(processes) - 15} more")

            yield CommandReturn(text="\n".join(lines))
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def kill(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle process killing."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars kill <name|PID> [-f]")
            return

        target = params[0]
        force = "-f" in params

        helper = await get_helper()
        result = await helper.kill_process(target, force=force)

        if result["success"]:
            yield CommandReturn(text=f"Process terminated: {target}")
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def ls(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle directory listing."""
        params = context.crt_params
        path = params[0] if params else "."
        show_hidden = "-a" in params

        helper = await get_helper()
        result = await helper.list_directory(path, show_hidden)

        if result["success"]:
            items = result.get("items", [])
            if not items:
                yield CommandReturn(text=f"Directory is empty: {result.get('path', path)}")
                return

            lines = [f"**Contents of `{result.get('path', path)}`**\n"]
            for item in items:
                icon = "📁" if item["type"] == "directory" else "📄"
                size_str = f" ({item['size']} bytes)" if item["size"] > 0 else ""
                lines.append(f"{icon} {item['name']}{size_str}")

            lines.append(f"\nTotal: {result.get('count', 0)} items")
            yield CommandReturn(text="\n".join(lines))
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Access denied')}")

    @staticmethod
    async def cat(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle file reading."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars cat <path>")
            return

        path = params[0]

        helper = await get_helper()
        result = await helper.read_file(path)

        if result["success"]:
            content = result.get("content", "")
            if result.get("is_binary"):
                yield CommandReturn(text=f"Binary file: {result.get('path', path)} ({result.get('size', 0)} bytes)")
            elif len(content) > 2000:
                yield CommandReturn(text=f"```\n{content[:2000]}\n```\n\n... (truncated)")
            else:
                yield CommandReturn(text=f"```\n{content}\n```")
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Access denied')}")

    @staticmethod
    async def write(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle file writing."""
        params = context.crt_params
        if len(params) < 2:
            yield CommandReturn(text="Usage: !tars write <path> <content>")
            return

        path = params[0]
        content = " ".join(params[1:])

        helper = await get_helper()
        result = await helper.write_file(path, content)

        if result["success"]:
            yield CommandReturn(text=f"File written: {result.get('path', path)}")
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def open(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle app/URL opening."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars open <app_name|url>")
            return

        target = params[0]
        is_url = target.startswith(("http://", "https://", "mailto:", "tel:"))

        helper = await get_helper()
        result = await helper.open_app(
            target if not is_url else None,
            url=target if is_url else None
        )

        if result["success"]:
            yield CommandReturn(text=f"Opened: {target}")
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def close(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle app closing."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars close <app_name> [-f]")
            return

        app_name = params[0]
        force = "-f" in params

        helper = await get_helper()
        result = await helper.close_app(app_name, force=force)

        if result["success"]:
            yield CommandReturn(text=f"Closed: {app_name}")
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

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
        PlannerTool.stop_task()
        SubprocessPlanner._remove_run_file()
        await _cleanup_browser()

        yield CommandReturn(text="🛑 Stop signal sent.\n\nIf the task doesn't stop, run in terminal:\n  touch /tmp/langtars_user_stop")

    @staticmethod
    async def logs(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle log viewing."""
        from collections import deque
        from pathlib import Path

        # Get number of lines to show (default 50)
        params = context.crt_params
        try:
            lines = int(params[0]) if params else 50
        except ValueError:
            lines = 50

        def _tail_file(path: Path, max_lines: int) -> str:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                return "".join(deque(f, maxlen=max_lines)).strip()

        log_files = [
            Path.home() / ".langtars" / "logs" / "langtars.log",
            Path("/tmp/langtars.log"),
            Path("/tmp/langtars_planner.log"),
            Path.home() / "Library" / "Logs" / "langtars.log",
        ]

        output_blocks = []
        for log_file in log_files:
            if not log_file.exists() or not log_file.is_file():
                continue
            try:
                content = _tail_file(log_file, lines)
            except Exception as e:
                output_blocks.append(f"📄 Logs from {log_file}:\n(read failed: {e})")
                continue

            if content:
                output_blocks.append(f"📄 Logs from {log_file}:\n{content}")

        if not output_blocks:
            yield CommandReturn(
                text=(
                    "📋 No logs found.\n\n"
                    "Expected primary log file:\n"
                    f"{Path.home() / '.langtars' / 'logs' / 'langtars.log'}\n\n"
                    "Please run any !tars command once, then retry `!tars logs`."
                )
            )
            return

        full_log = "\n\n".join(output_blocks)
        # Keep response size conservative for IM platform limits.
        if len(full_log) > 3200:
            full_log = "...(truncated)\n" + full_log[-3000:]
        yield CommandReturn(text=full_log)

    @staticmethod
    async def result(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Get last background task result."""
        if BackgroundTaskManager.is_running():
            yield CommandReturn(text="⏳ Task is still running. Please try again in a moment.")
            return

        pending = BackgroundTaskManager.get_pending_result()
        if pending:
            BackgroundTaskManager._pending_result = None
            yield CommandReturn(text=f"📬 Last task result (fallback):\n\n{pending}")
            return

        last = BackgroundTaskManager.get_last_result()
        if last:
            yield CommandReturn(text=f"📄 Last task result:\n\n{last}")
            return

        yield CommandReturn(text="No task result found.")

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
            
            yield CommandReturn(text=f"✅ 已停止当前任务，收到新指令：{new_instruction}\n\n请使用 !tars do {new_instruction} 来执行新任务。")
            return
        
        # No task running, just inform user to use !tars do
        yield CommandReturn(text=f"ℹ️ 当前没有正在执行的任务。\n\n请使用 !tars do {new_instruction} 来执行任务。")

    @staticmethod
    async def top(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle app listing."""
        helper = await get_helper()
        result = await helper.list_apps()

        if result["success"]:
            apps = result.get("apps", [])
            if not apps:
                yield CommandReturn(text="No applications running.")
                return

            lines = ["**Running Applications:**\n"]
            lines.append("\n".join(f"• {app}" for app in apps))
            yield CommandReturn(text="\n".join(lines))
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def info(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle system info display."""
        helper = await get_helper()
        result = await helper.get_system_info()

        if result["success"]:
            info = result.get("info", {})
            lines = ["**System Information:**\n"]
            for key, value in info.items():
                if isinstance(value, dict):
                    continue
                lines.append(f"• **{key}**: {value}")
            yield CommandReturn(text="\n".join(lines))
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def search(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle file search."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="Usage: !tars search <pattern> [path]")
            return

        pattern = params[0]
        path = params[1] if len(params) > 1 else "."

        helper = await get_helper()
        result = await helper.search_files(pattern, path)

        if result["success"]:
            files = result.get("files", [])
            if not files:
                yield CommandReturn(text=f"No files found matching '{pattern}'")
                return

            lines = [f"**Search Results for '{pattern}':**\n"]
            for f in files[:20]:
                lines.append(f"• {f}")

            if len(files) > 20:
                lines.append(f"... and {len(files) - 20} more")

            yield CommandReturn(text="\n".join(lines))
        else:
            yield CommandReturn(text=f"Failed: {result.get('error', 'Unknown error')}")

    @staticmethod
    async def default(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle default case: answer pending question, otherwise show help."""
        answer = " ".join(context.crt_params).strip() if context.crt_params else ""

        if BackgroundTaskManager.has_pending_user_question():
            if not answer:
                pending_q = BackgroundTaskManager.get_pending_user_question() or {}
                msg = "🤔 插件正在等你回答:\n\n"
                msg += f"问题: {pending_q.get('question', '')}\n"
                options = pending_q.get("options", []) or []
                if options:
                    msg += "可选项: " + " / ".join(str(x) for x in options) + "\n"
                msg += "\n请回复: !tars <你的回答>"
                yield CommandReturn(text=msg)
                return

            if BackgroundTaskManager.submit_user_input(answer):
                yield CommandReturn(text=f"✅ 已收到你的回答：{answer}")
            else:
                yield CommandReturn(text="⚠️ 当前没有可接收回答的问题。")
            return

        yield CommandReturn(text=LanTARSCommand._help_text())

    @staticmethod
    async def help(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Show explicit help command."""
        yield CommandReturn(text=LanTARSCommand._help_text())

    @staticmethod
    async def auto(_self_cmd: Command, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
        """Handle autonomous task planning using ReAct loop."""
        params = context.crt_params
        if not params:
            yield CommandReturn(text="""Usage: !tars auto <task description>

Example:
  !tars auto Open Safari and search for AI news
""")
            return

        # Check if a task is already running
        from components.tools.planner import PlannerTool, TrueSubprocessPlanner, PlannerExecutor, SubprocessPlanner

        if BackgroundTaskManager.is_running() or TrueSubprocessPlanner.is_running():
            yield CommandReturn(text="⚠️ A task is already running. Use !tars stop to stop it first.")
            return

        task = " ".join(params)

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
        BackgroundTaskManager.set_task_status(
            task_description=task,
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
                start_msg = f"🚀 任务已启动！\n\n任务: {task[:100]}{'...' if len(task) > 100 else ''}\n\n使用 !tars what 查看进度"
                await _self_cmd.plugin.send_message(
                    bot_uuid=bot_uuid_notify,
                    target_type=notify_target_type,
                    target_id=notify_target_id,
                    message_chain=MessageChain([Plain(text=start_msg)]),
                )
        except Exception as e:
            logger.warning(f"Failed to send task start notification: {e}")

        # Start task in background and immediately return
        # This allows stop command to be processed while task runs
        try:
            bot_uuid: str | None = None
            try:
                bot_uuid = await context.get_bot_uuid()
                logger.info(f"[AUTO] Got bot_uuid from context: {bot_uuid}")
            except Exception as e:
                logger.warning(f"Failed to get bot uuid for background send: {e}")
            if not bot_uuid:
                try:
                    conversation = getattr(context.session, "using_conversation", None)
                    if conversation and getattr(conversation, "bot_uuid", None):
                        bot_uuid = str(conversation.bot_uuid)
                        logger.info(f"[AUTO] Got bot_uuid from conversation: {bot_uuid}")
                except Exception:
                    pass
            target_type = context.session.launcher_type.value
            raw_target_id = context.session.launcher_id
            logger.info(f"[AUTO] target_type={target_type}, raw_target_id={raw_target_id}, bot_uuid={bot_uuid}")

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
                logger.info(f"[AUTO] _auto_execute_result_reply called, bot_uuid={bot_uuid}, target_type={target_type}, raw_target_id={raw_target_id}")
                pending = BackgroundTaskManager.get_pending_result()
                if pending:
                    msg = f"📬 Last task result (fallback):\n\n{pending}"
                else:
                    last = BackgroundTaskManager.get_last_result()
                    if last:
                        msg = f"📄 Last task result:\n\n{last}"
                    else:
                        msg = "No task result found."
                logger.info(f"[AUTO] Message to send: {msg[:100]}...")
                try:
                    if not bot_uuid:
                        raise RuntimeError("missing bot_uuid")
                    sent = False
                    errors: list[str] = []
                    for cid in _candidate_target_ids(raw_target_id):
                        try:
                            logger.info(f"[AUTO] Trying to send to bot_uuid={bot_uuid}, target_type={target_type}, target_id={cid}")
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
                            logger.warning(f"[AUTO] send_message failed for {cid}: {send_err}")
                            errors.append(f"{cid!r}: {send_err}")
                    if sent:
                        # Only clear pending after a successful auto send.
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
                        logger.warning(f"[AUTO] Browser cleanup reported failure ({phase}): {result}")
                except Exception as cleanup_err:
                    logger.warning(f"[AUTO] Browser cleanup failed ({phase}): {cleanup_err}")

            async def run_task():
                try:
                    # Keep the run file semantics so stop checks stay consistent
                    SubprocessPlanner._create_run_file()

                    executor = PlannerExecutor()
                    async for partial_result in executor.execute_task_streaming(
                        task=task,
                        max_iterations=max_iterations,
                        llm_model_uuid=llm_model_uuid,
                        plugin=_self_cmd.plugin,
                        helper_plugin=_self_cmd.plugin,
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
                    SubprocessPlanner._remove_run_file()
                    if bool(config.get("auto_cleanup_browser_on_finish", False)):
                        await _cleanup_browser("run_task.finally")
                    BackgroundTaskManager._task_running = False
                    BackgroundTaskManager._current_step = "任务已完成"

            async def run_subprocess_task():
                try:
                    async for partial_result in TrueSubprocessPlanner.execute_in_subprocess(
                        task=task,
                        max_iterations=max_iterations,
                        llm_model_uuid=llm_model_uuid,
                        plugin=_self_cmd.plugin,
                        helper_plugin=_self_cmd.plugin,
                        session=context.session,
                        query_id=context.query_id
                    ):
                        # Store latest result for stop command to retrieve
                        BackgroundTaskManager._last_result = partial_result
                        # Small delay to allow stop command to be processed
                        await asyncio.sleep(0.1)
                    if BackgroundTaskManager._last_result:
                        await _reply_background(BackgroundTaskManager._last_result)
                    else:
                        await _reply_background("✅ Task completed.")
                    await _auto_execute_result_reply()
                except Exception as e:
                    import traceback
                    BackgroundTaskManager._last_result = f"Error: {str(e)}\n{traceback.format_exc()}"
                    await _reply_background(f"❌ Task error:\n{BackgroundTaskManager._last_result}")
                    await _auto_execute_result_reply()
                finally:
                    if bool(config.get("auto_cleanup_browser_on_finish", False)):
                        await _cleanup_browser("run_subprocess_task.finally")
                    BackgroundTaskManager._task_running = False
                    BackgroundTaskManager._current_step = "任务已完成"

            # NOTE:
            # LLM invocation depends on plugin_runtime_handler from the current runtime.
            # This handler is not available in standalone subprocess-created plugin instances.
            # Therefore default to in-process background execution; keep subprocess path optional.
            use_true_subprocess = bool(config.get("planner_use_true_subprocess", False))
            BackgroundTaskManager._last_result = None
            BackgroundTaskManager._pending_result = None
            bg_task = asyncio.create_task(run_subprocess_task() if use_true_subprocess else run_task())
            BackgroundTaskManager._task_running = True
            BackgroundTaskManager._bg_task = bg_task

            if use_true_subprocess:
                yield CommandReturn(text="🚀 Task started in background (subprocess mode). Use !tars stop to cancel.\n")
            else:
                yield CommandReturn(text="🚀 Task started in background. Use !tars stop to cancel.\n")

        except Exception as e:
            import traceback
            yield CommandReturn(text=f"Error starting task: {str(e)}\n\n{traceback.format_exc()}")
