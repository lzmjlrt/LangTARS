# LangTARS Command Handler
# Handle direct commands like /shell, /ps, /ls, etc.

from __future__ import annotations

import asyncio
import logging
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
        ]

        import platform
        if platform.system() == "Windows":
            log_files.extend([
                Path.home() / "AppData" / "Local" / "langtars" / "langtars.log",
                Path(r"C:\Temp\langtars.log"),
                Path(r"C:\Temp\langtars_planner.log"),
            ])
        else:
            log_files.extend([
                Path("/tmp/langtars.log"),
                Path("/tmp/langtars_planner.log"),
                Path.home() / "Library" / "Logs" / "langtars.log",
            ])

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
        """Handle default case - show help."""
        import platform
        sys_name = "Windows PC" if platform.system() == "Windows" else "Mac"
        stop_hint = ("To stop a running task:\n  !tars stop") if platform.system() == "Windows" else (
            "To stop a running task, run in terminal:\n  touch /tmp/langtars_user_stop"
        )
        help_text = f"""LangTARS - Control your {sys_name} through IM messages

Available commands:
  !tars shell <command>   - Execute shell command
  !tars ps [filter]       - List running processes
  !tars kill <pid|name>   - Kill a process
  !tars ls [path]         - List directory contents
  !tars cat <path>        - Read file content
  !tars write <path> <content> - Write file
  !tars open <app|url>   - Open an application or URL
  !tars close <app>      - Close an application
  !tars top              - List running applications
  !tars logs [lines]     - View recent logs
  !tars result           - Get last auto task result
  !tars info             - Show system information
  !tars search <pattern> - Search files
  !tars auto <task>      - Autonomous task planning (AI-powered)

{stop_hint}

Examples:
  !tars info
  !tars shell {"dir" if platform.system() == "Windows" else "ls -la"}
  !tars ps python
  !tars open {"Edge" if platform.system() == "Windows" else "Safari"}
  !tars auto {"Open Edge" if platform.system() == "Windows" else "Open Safari"} and search for AI news
"""
        yield CommandReturn(text=help_text)

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

        # Start task in background and immediately return
        # This allows stop command to be processed while task runs
        try:
            bot_uuid: str | None = None
            try:
                bot_uuid = await context.get_bot_uuid()
            except Exception as e:
                logger.warning(f"Failed to get bot uuid for background send: {e}")
            if not bot_uuid:
                try:
                    conversation = getattr(context.session, "using_conversation", None)
                    if conversation and getattr(conversation, "bot_uuid", None):
                        bot_uuid = str(conversation.bot_uuid)
                except Exception:
                    pass
            target_type = context.session.launcher_type.value
            raw_target_id = context.session.launcher_id

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
                pending = BackgroundTaskManager.get_pending_result()
                if pending:
                    msg = f"📬 Last task result (fallback):\n\n{pending}"
                else:
                    last = BackgroundTaskManager.get_last_result()
                    if last:
                        msg = f"📄 Last task result:\n\n{last}"
                    else:
                        msg = "No task result found."
                try:
                    if not bot_uuid:
                        raise RuntimeError("missing bot_uuid")
                    sent = False
                    errors: list[str] = []
                    for cid in _candidate_target_ids(raw_target_id):
                        try:
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
                    await _cleanup_browser("run_task.finally")
                    BackgroundTaskManager._task_running = False

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
                    await _cleanup_browser("run_subprocess_task.finally")
                    BackgroundTaskManager._task_running = False

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
