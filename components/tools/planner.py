# ReAct loop for autonomous task planning and execution

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import multiprocessing
from pathlib import Path
from typing import Any, AsyncGenerator

from components.helpers.logging_setup import setup_langtars_file_logging

# Ensure root logger has stream + file handlers even if host already configured logging
setup_langtars_file_logging()
logger = logging.getLogger(__name__)

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session
from langbot_plugin.api.entities.builtin.provider import message as provider_message
from langbot_plugin.api.entities.builtin.resource import tool as resource_tool

from .planner_tools import BasePlannerTool
from .planner_tools.registry import ToolRegistry


class PlannerTool(Tool):
    """Planner tool - ReAct loop for autonomous task execution"""

    __kind__ = "Tool"

    # Class variable for rate limiting
    _last_llm_call_time: float = 0.0

    # Class variable for LLM call count tracking
    _llm_call_count: int = 0

    # Class variable for task pause/stop control
    _task_stopped: bool = False
    _current_task_info: dict = {}
    _invalid_response_count: int = 0  # Track consecutive invalid LLM responses

    # Tool registry instance
    _tool_registry: ToolRegistry | None = None

    # Subprocess for running planner
    _subprocess: Any = None
    _planner_process: Any = None  # subprocess.Popen instance

    # Current running asyncio task (for cancellation)
    _current_asyncio_task: Any = None
    # Event to signal task stop
    _stop_event: asyncio.Event | None = None

    @classmethod
    def stop_task(cls, task_id: str = "default") -> bool:
        """Stop the current running task by killing the subprocess"""
        logger.warning(f"stop_task() called, setting _task_stopped=True")
        cls._task_stopped = True
        logger.warning(f"stop_task() completed, _task_stopped={cls._task_stopped}")

        # Signal the stop event if it exists
        if cls._stop_event:
            try:
                cls._stop_event.set()
                logger.warning("Stop event set")
            except Exception as e:
                logger.warning(f"Error setting stop event: {e}")

        # Try to cancel the asyncio task if running
        if cls._current_asyncio_task and not cls._current_asyncio_task.done():
            try:
                cls._current_asyncio_task.cancel()
                logger.warning("Cancelled asyncio task")
            except Exception as e:
                logger.warning(f"Error cancelling task: {e}")

        # Kill the subprocess if running
        if cls._planner_process:
            try:
                cls._planner_process.terminate()
                # Force kill if still running after 1 second
                try:
                    cls._planner_process.wait(timeout=1)
                except:
                    try:
                        cls._planner_process.kill()
                    except:
                        pass
                cls._planner_process = None
            except Exception as e:
                logger.debug(f"Error terminating process: {e}")
                cls._planner_process = None

        return True

    @classmethod
    def set_asyncio_task(cls, task: Any) -> None:
        """Set the current asyncio task for cancellation support"""
        cls._current_asyncio_task = task

    @classmethod
    def is_task_stopped(cls) -> bool:
        """Check if the current task has been stopped (checks memory flag + user stop file)"""
        # Check memory flag first
        if cls._task_stopped:
            return True
        # Also check if user created the stop file
        if SubprocessPlanner._check_user_stop_file():
            cls._task_stopped = True
            SubprocessPlanner._clear_user_stop_file()  # Clear the file after detecting
            return True
        return False

    @classmethod
    def reset_task_state(cls) -> None:
        """Reset task state for a new task"""
        cls._task_stopped = False
        cls._current_task_info = {}
        cls._llm_call_count = 0
        cls._invalid_response_count = 0
        cls._subprocess = None
        cls._planner_process = None
        cls._stop_event = asyncio.Event()
        # Clear user stop file when starting a new task
        SubprocessPlanner._clear_user_stop_file()

    SYSTEM_PROMPT = """You are a task planning assistant. Your job is to help users accomplish tasks on their Mac by intelligently calling tools.

AVAILABLE TOOLS:
You MUST use the tools listed below to accomplish tasks. NEVER claim you cannot do something without trying the tools first.

## Response Format - VERY IMPORTANT:

When you need to execute a tool, you MUST respond with ONLY a JSON object in this exact format:
{"tool": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}

When the task is COMPLETED, respond with ONLY:
DONE: Your summary here

When the task is in progress but not yet complete, respond with ONLY:
WORKING: Description of what you are currently doing (e.g., "Fetching page content...", "Waiting for page to load...")

When you need a skill that doesn't exist, respond with ONLY:
NEED_SKILL: Description of what capability you need

## CRITICAL: After tool execution, you MUST respond with DONE

After any tool returns {"success": true}, you MUST immediately return DONE: with a summary.
- Opening an app? DONE: Opened [app name]
- Navigated to a website? DONE: Opened [URL]
- Executed a command? DONE: Command executed successfully
- DO NOT keep calling the same tool repeatedly!

## Examples:

User: "List files in current directory"
Response: {"tool": "shell", "arguments": {"command": "ls -la"}}
# Tool result: {"success": true, "stdout": "...", ...}
# Then respond with:
DONE: Listed files in current directory

User: "Open Safari and go to github.com"
Response: {"tool": "safari_navigate", "arguments": {"url": "https://github.com"}}
# Tool result: {"success": true, ...}
# Then respond with:
DONE: Opened github.com in Safari

User: "Open Safari, navigate to github.com and get content"
Response: {"tool": "safari_navigate", "arguments": {"url": "https://github.com"}}
# Tool result: {"success": true, ...}
Response: WORKING: Navigated to github.com, now fetching page content...
Response: {"tool": "safari_get_content", "arguments": {}}
# Tool result: {"success": true, "stdout": "Title: GitHub, ...", ...}
# Then respond with:
DONE: GitHub page content: [summary of content]

User: "Open Chrome and search for AI news"
Response: {"tool": "chrome_navigate", "arguments": {"url": "https://www.bing.com/search?q=AI+news"}}
# Tool result: {"success": true, ...}
# Then respond with:
DONE: Opened Chrome and searched for AI news

User: "Open a website"
Response: {"tool": "browser_navigate", "arguments": {"url": "https://example.com"}}
# After receiving success result, respond with:
DONE: Opened the website

User: "What's the weather in Beijing?"
Response: {"tool": "browser_navigate", "arguments": {"url": "https://www.bing.com/search?q=北京天气"}}
# Tool result: {"success": true, ...}
Response: WORKING: Got search results, now clicking first result to get actual weather...
Response: {"tool": "browser_click", "arguments": {"selector": ".b_adClick"}}
# Tool result: {"success": true, ...}
# IMPORTANT: After clicking, MUST immediately get content!
Response: WORKING: Clicked result, now extracting weather data...
Response: {"tool": "browser_get_content", "arguments": {}}
# Tool result: {"success": true, "content": "北京天气预报: 晴, 15°C, 湿度45%..."}
# Then respond with:
DONE: 北京今天天气晴朗，气温15°C，湿度45%。

User: "Task complete, show result"
Response: DONE: Successfully completed the task...

User: "Open one of two possible websites but not sure which one"
Response: {"tool": "ask_user", "arguments": {"question": "你想打开哪一个？", "options": ["A", "B"]}}
# Tool result: {"success": true, "answer": "..."}
# Then continue with the chosen option and finish with DONE.

## Browser Selection Rules - VERY IMPORTANT:
- If user says "open website" or "go to website" WITHOUT specifying browser → Use browser_navigate (Playwright)
- If user says "open Safari" or "use Safari" → Use safari_navigate (controls real Safari app)
- If user says "open Chrome" or "use Chrome" → Use chrome_navigate (controls real Chrome app)
- For Safari: use safari_open, safari_navigate, safari_get_content, safari_click, safari_type, safari_press
- For Chrome: use chrome_open, chrome_navigate, chrome_get_content, chrome_click, chrome_type, chrome_press
- For general web automation: use browser_navigate, browser_click, browser_type, browser_screenshot

## Important Rules:
1. ALWAYS try to use available tools before giving up
2. ALWAYS respond with valid JSON when calling tools
3. NEVER respond with natural language text when tools are needed
4. Use browser_navigate for general web automation (Playwright)
5. Use safari_* tools when user specifically mentions Safari
6. Use chrome_* tools when user specifically mentions Chrome
7. Use shell for terminal commands
8. Use fetch_url to get web page content
9. After a tool returns success ({"success": true}):
   - If you already have the FINAL answer → respond with "DONE: Your summary"
   - If you need MORE information from the page → respond with "WORKING: [what you're doing]" then call more tools
   - For example, after navigating to a weather page, use browser_get_content to extract actual weather data
10. If user asks for content/summary, fetch it first THEN return DONE with the summary
11. NEVER respond with natural language - always use JSON or DONE: format
12. When navigating to a search results page (e.g., Bing search), you MUST either:
    - Click on a relevant result to go to the actual page, then get its content
    - Or use browser_get_content to extract information from the search results
    - DON'T just return DONE after seeing search results - you need to get the actual content!
13. IMPORTANT - Click LIMIT: After clicking a search result link, you MUST immediately call browser_get_content to extract the actual content. NEVER click more than once - if the first click doesn't work, use browser_get_content on the current page instead.
14. Use browser_get_content to get the actual text/content from the page after any navigation or click. This is how you extract useful information!
15. If the user's request is ambiguous or there are multiple choices, call ask_user first to clarify, then continue execution.
16. For ask_user responses, the user will reply in chat using `!tars <answer>`. Use the returned `answer` to continue.

If no tool can accomplish the user's request, then respond with NEED_SKILL: and describe what you need.
"""

    async def _get_tool_registry(self, plugin=None) -> ToolRegistry:
        """Get or create the tool registry"""
        if PlannerTool._tool_registry is None:
            # Use provided plugin or try to get from self
            p = plugin if plugin else getattr(self, 'plugin', None)
            if p:
                PlannerTool._tool_registry = ToolRegistry(p)
                await PlannerTool._tool_registry.initialize()
        return PlannerTool._tool_registry

    @classmethod
    def set_current_task(cls, task_id: str, task_description: str) -> None:
        """Set the current running task info"""
        cls._current_task_info = {
            "task_id": task_id,
            "task_description": task_description,
        }

    @classmethod
    def get_current_task(cls) -> dict:
        """Get the current running task info"""
        return cls._current_task_info

    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        """Execute the planner to complete a task using ReAct loop."""
        task = params.get('task', '')
        max_iterations = params.get('max_iterations', 5)
        llm_model_uuid = params.get('llm_model_uuid', '')

        if not task:
            return "Error: No task provided. Please specify a task to execute."

        # Try to get the plugin instance which has invoke_llm and get_llm_models methods
        plugin = getattr(self, 'plugin', None)

        if not plugin:
            return "Error: Plugin context not available. Please use !tars auto command instead."

        # Get configured model from plugin config
        config = plugin.get_config()
        configured_model_uuid = config.get('planner_model_uuid', '')

        # Auto-detect model
        if not llm_model_uuid:
            try:
                models = await plugin.get_llm_models()
                if not models:
                    return "Error: No LLM models available. Please configure a model in the pipeline settings."

                if configured_model_uuid:
                    for model in models:
                        if isinstance(model, dict) and model.get('uuid') == configured_model_uuid:
                            llm_model_uuid = configured_model_uuid
                            break
                    else:
                        llm_model_uuid = models[0].get('uuid', '') if isinstance(models[0], dict) else models[0]
                else:
                    first_model = models[0]
                    if isinstance(first_model, dict):
                        llm_model_uuid = first_model.get('uuid', '')
                    else:
                        llm_model_uuid = first_model

                if not llm_model_uuid:
                    return "Error: No LLM models available or model does not have a valid UUID."
            except Exception as e:
                return f"Error: Failed to get available models: {str(e)}"

        # Initialize tool registry and load dynamic tools
        registry = await self._get_tool_registry(plugin)
        config = plugin.get_config()
        auto_load_mcp = config.get('planner_auto_load_mcp', True)

        if auto_load_mcp:
            try:
                dynamic_tools = await registry.load_dynamic_tools()
                if dynamic_tools:
                    logger.debug(f"Loaded {len(dynamic_tools)} dynamic tools")
            except Exception as e:
                logger.debug(f"Failed to load dynamic tools: {e}")

        # Import main module to get helper methods
        from main import LangTARS
        helper_plugin = LangTARS()
        # Pass the config to the helper plugin so browser tools work
        helper_plugin.config = config.copy()
        await helper_plugin.initialize()

        return await self.execute_task(
            task=task,
            max_iterations=max_iterations,
            llm_model_uuid=llm_model_uuid,
            plugin=plugin,
            helper_plugin=helper_plugin,
            registry=registry,
            session=session,
            query_id=query_id
        )

    async def execute_task(
        self,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin: 'LangTARSPlugin',
        helper_plugin: 'LangTARS' = None,
        registry: ToolRegistry | None = None,
        session=None,
        query_id: int = 0,
    ) -> str:
        """Execute task with ReAct loop using provided plugin instance."""
        # Reset task state for new task (this clears _task_stopped)
        PlannerTool.reset_task_state()
        PlannerTool.set_current_task("default", task)

        if not task:
            return "Error: No task provided."

        if not llm_model_uuid:
            return "Error: No LLM model specified. Please configure a model in the pipeline settings."

        # Initialize registry if not provided
        if registry is None and plugin:
            registry = await self._get_tool_registry(plugin)

        # Get rate limit from config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))

        # Get tools description from registry
        tools_description = ""
        if registry:
            try:
                tools_description = registry.get_tools_description()
            except Exception as e:
                logger.error(f"获取 tools_description 失败: {e}")

        # Build initial messages - start with system prompt
        messages = [
            provider_message.Message(
                role="system",
                content=self.SYSTEM_PROMPT
            ),
        ]
        # For new task, don't load any session history - start fresh
        # This ensures each new auto command is independent and not affected by previous tasks
        logger.debug("Starting new task - not loading session history")

        # Add the current task with tools description
        user_message = f"{task}\n\nIMPORTANT: Use a tool to complete this task. Available tools:\n{tools_description}\n\nRemember: Respond with JSON format only: {{\"tool\": \"name\", \"arguments\": {{...}}}}"
        messages.append(provider_message.Message(
            role="user",
            content=user_message
        ))

        # ReAct loop
        for iteration in range(max_iterations):
            try:
                # Check if task has been stopped
                if PlannerTool.is_task_stopped():
                    return "Task has been stopped by user."

                # Check if stopped before LLM call
                if PlannerTool.is_task_stopped():
                    return "Task has been stopped by user."

                # Rate limiting: wait if necessary
                current_time = time.time()
                time_since_last_call = current_time - PlannerTool._last_llm_call_time
                if time_since_last_call < rate_limit_seconds:
                    wait_time = rate_limit_seconds - time_since_last_call
                    logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before LLM call")
                    await asyncio.sleep(wait_time)
                    # Check if stopped during sleep
                    if PlannerTool.is_task_stopped():
                        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                        return "Task has been stopped by user."
                PlannerTool._last_llm_call_time = time.time()

                # Increment LLM call count
                PlannerTool._llm_call_count += 1
                logger.info(f"LLM 调用开始 (第 {PlannerTool._llm_call_count} 次), task: {task[:50]}...")

                # Run LLM call with periodic stop check
                try:
                    async def call_llm_with_stop_check():
                        """Call LLM and periodically check for stop signal"""
                        llm_task = asyncio.create_task(plugin.invoke_llm(
                            llm_model_uuid=llm_model_uuid,
                            messages=messages,
                            funcs=[]
                        ))

                        while not llm_task.done():
                            # Check both in-memory flag, user stop file, and run file
                            is_stopped = PlannerTool.is_task_stopped()
                            file_exists = os.path.exists(SubprocessPlanner._STOP_FILE)
                            user_stop_exists = SubprocessPlanner._check_user_stop_file()
                            if is_stopped or user_stop_exists:
                                llm_task.cancel()
                                raise asyncio.CancelledError("Task stopped during LLM call")
                            # Also check run file
                            if not file_exists:
                                llm_task.cancel()
                                raise asyncio.CancelledError("Run file deleted during LLM call")
                            await asyncio.sleep(0.05)

                        return await llm_task

                    response = await call_llm_with_stop_check()
                except asyncio.CancelledError:
                    PlannerTool.stop_task()
                    SubprocessPlanner._clear_user_stop_file()
                    logger.info("Task cancelled via CancelledError")
                    return "Task has been stopped by user."

                # Check if stopped after LLM call (important for interrupt)
                if PlannerTool.is_task_stopped():
                    logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                    return "Task has been stopped by user."

                # Check if there's content (non-tool response)
                if response.content and not response.tool_calls:
                    content_str = str(response.content)
                    if content_str.strip().upper().startswith("DONE:"):
                        result = content_str[5:].strip()
                        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                        return result

                    # Check if LLM indicates it needs a skill
                    if content_str.strip().upper().startswith("NEED_SKILL:"):
                        skill_needed = content_str[11:].strip()
                        logger.info(f"需要技能: {skill_needed}")

                        # Try to auto-install skill and retry
                        retry_result = await self._try_auto_install_and_retry(
                            skill_needed, messages, task, helper_plugin, registry, plugin
                        )
                        if retry_result is not None:
                            # Successfully installed skill and retried, return the result
                            logger.info(f"Skill自动安装并重试成功，共调用 {PlannerTool._llm_call_count} 次")
                            return retry_result

                        # If auto-install failed, return suggestion message
                        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                        return self._generate_skill_suggestion(skill_needed)

                    # Check if LLM indicates task is in progress
                    if content_str.strip().upper().startswith("WORKING:"):
                        working_msg = content_str[8:].strip()
                        logger.info(f"LLM 正在工作中: {working_msg}")
                        
                        # Update background task status
                        try:
                            from components.commands.langtars import BackgroundTaskManager
                            BackgroundTaskManager.set_task_status(
                                task_description=task,
                                step=working_msg,
                                tool=""
                            )
                        except Exception as e:
                            logger.debug(f"Failed to update task status: {e}")
                        
                        # Reset invalid response count since this is a valid state
                        PlannerTool._invalid_response_count = 0
                        # Add as user message and continue to next iteration
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=f"继续执行任务。{working_msg}"
                            )
                        )
                        continue

                    # Try to parse JSON tool call from content
                    tool_call = self._parse_tool_call_from_content(content_str)
                    if tool_call:
                        result = await self._execute_tool(
                            tool_call, helper_plugin or plugin, registry
                        )

                        # Check if user provided a new instruction
                        if isinstance(result, dict) and result.get("new_task"):
                            new_task = result.get("new_task")
                            logger.info(f"用户提供了新任务: {new_task}")
                            return f"用户提供了新任务: {new_task}"

                        # Check if stopped after tool execution
                        if PlannerTool.is_task_stopped():
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task stopped by user. Last result:\n{result}"

                        # For JSON format responses (not tool_calls), send result as user message
                        # instead of tool_result to avoid Bedrock API tool_use_id mismatch error
                        hint = f"""
工具执行结果：{json.dumps(result)[:500]}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到最终答案 → 返回 DONE: 答案
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

关键：不要重复执行相同的工具！"""
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=hint
                            )
                        )

                        if iteration == max_iterations - 1:
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task reached maximum iterations ({max_iterations}). Progress so far:\n{result}"
                        continue

                    if content_str.strip():
                        # Count consecutive invalid responses
                        PlannerTool._invalid_response_count += 1
                        invalid_response_count = PlannerTool._invalid_response_count

                        # If too many consecutive invalid responses, force end
                        if invalid_response_count >= 3:
                            logger.info(f"LLM 返回了 {invalid_response_count} 次无效响应，强制结束任务")
                            return f"无法完成任务。LLM 连续返回了 {invalid_response_count} 次无效响应（未调用工具）。\n\n最后响应：\n{content_str[:500]}"

                        messages.append(response)
                        continue

                # Check if stopped before tool execution
                if PlannerTool.is_task_stopped():
                    logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                    return "Task has been stopped by user."

                # Handle structured tool calls
                if response.tool_calls:
                    for tool_call in response.tool_calls:
                        result = await self._execute_tool(
                            tool_call, helper_plugin or plugin, registry
                        )

                        # Check if user provided a new instruction
                        if isinstance(result, dict) and result.get("new_task"):
                            new_task = result.get("new_task")
                            logger.info(f"用户提供了新任务: {new_task}")
                            return f"用户提供了新任务: {new_task}"

                        # Check if stopped after tool execution
                        if PlannerTool.is_task_stopped():
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task stopped by user. Last result:\n{result}"

                        messages.append(
                            provider_message.Message(
                                role="tool",
                                content=json.dumps(result),
                                tool_call_id=tool_call.id
                            )
                        )

                        # Add a hint to prompt LLM to continue if task is not complete
                        hint = f"""
上一个工具执行结果：{json.dumps(result)[:500]}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到页面内容 → 立即返回 DONE: 总结内容
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

关键：不要重复执行相同的工具！"""
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=hint
                            )
                        )

                        if iteration == max_iterations - 1:
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task reached maximum iterations ({max_iterations}). Progress so far:\n{result}"
                        # Continue to next iteration - tool result has been added to messages
                        logger.debug(f"工具执行完成，进入下一次迭代 (iteration={iteration+1})")
                        continue
                else:
                    if response.content:
                        content_str = str(response.content)
                        if content_str.strip().upper().startswith("DONE:"):
                            result = content_str[5:].strip()
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return result
                        # Check if LLM indicates task is in progress
                        if content_str.strip().upper().startswith("WORKING:"):
                            working_msg = content_str[8:].strip()
                            logger.info(f"LLM 正在工作中: {working_msg}")
                            # Reset invalid response count
                            PlannerTool._invalid_response_count = 0
                            messages.append(
                                provider_message.Message(
                                    role="user",
                                    content=f"继续执行任务。{working_msg}"
                                )
                            )
                            continue
                        # Check if LLM indicates it needs a skill
                        if content_str.strip().upper().startswith("NEED_SKILL:"):
                            skill_needed = content_str[11:].strip()
                            logger.info(f"需要技能: {skill_needed}")

                            # Try to auto-install skill and retry
                            retry_result = await self._try_auto_install_and_retry(
                                skill_needed, messages, task, helper_plugin, registry, plugin
                            )
                            if retry_result is not None:
                                # Successfully installed skill and retried, return the result
                                logger.info(f"Skill自动安装并重试成功，共调用 {PlannerTool._llm_call_count} 次")
                                return retry_result

                            # If auto-install failed, return suggestion message
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return self._generate_skill_suggestion(skill_needed)

            except Exception as e:
                import traceback
                error_msg = str(e)
                logger.error(f"执行异常: {error_msg}")
                logger.error(traceback.format_exc())
                # Check for specific error types
                if "429" in error_msg or "rate limit" in error_msg.lower():
                    return f"""错误: LLM API 请求过于频繁或余额不足。

请检查:
1. 账户是否有足够的余额
2. 是否开启了速率限制

可以稍后再试，或等待几秒钟后重试。

错误详情: {error_msg[:200]}"""
                logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                return f"Error during execution: {error_msg}"

        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
        return f"Task reached maximum iterations ({max_iterations}) without completion."

    def _generate_skill_suggestion(self, skill_needed: str) -> str:
        """Generate a suggestion for the user when a skill is needed."""
        # Check if skill loader is available
        skill_info = ""
        install_command = ""
        found_skills = []

        if PlannerTool._tool_registry and PlannerTool._tool_registry._skill_loader:
            try:
                # Try to search for relevant skills
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                found_skills = loop.run_until_complete(
                    PlannerTool._tool_registry._skill_loader.search_skills(skill_needed)
                )
                loop.close()

                if found_skills:
                    skill_info = "\n\n找到以下相关 Skills:\n"
                    for skill in found_skills[:5]:  # Show up to 5 skills
                        skill_info += f"- {skill.name}: {skill.description}\n"

                    # Try to auto-install the first matching skill
                    first_skill = found_skills[0]
                    install_result = self._try_auto_install(first_skill.name)
                    if install_result["success"]:
                        return f"""我发现了相关技能「{first_skill.name}」，正在自动安装...

安装成功！技能「{first_skill.name}」已安装。

请再次发送任务，我将使用新安装的技能来完成你的请求。
"""
            except Exception as e:
                logger.debug(f"Failed to search skills: {str(e)}")

        # If no skills found or auto-install failed, provide manual instructions
        return f"""抱歉，我无法完成这个任务，因为缺少必要的工具/技能。

需要的技能: {skill_needed}{skill_info}

"""

    def _try_auto_install(self, skill_name: str) -> dict[str, Any]:
        """Try to automatically install a skill"""
        if not PlannerTool._tool_registry or not PlannerTool._tool_registry._skill_loader:
            return {"success": False, "error": "Skill loader not available"}

        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                PlannerTool._tool_registry._skill_loader.install_skill(skill_name)
            )
            loop.close()
            return result
        except Exception as e:
            logger.debug(f"Auto-install failed: {e}")
            return {"success": False, "error": str(e)}

    async def _try_auto_install_and_retry(
        self,
        skill_needed: str,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        plugin,
    ) -> str | None:
        """
        Try to automatically install a skill and retry the task.
        Returns the result if successful, None if failed.
        """
        if not registry or not registry._skill_loader:
            logger.debug("Skill loader not available for auto-install")
            return None

        try:
            # Search for relevant skills
            logger.info(f"正在搜索Skill: {skill_needed}")
            found_skills = await registry._skill_loader.search_skills(skill_needed)
            logger.debug(f"搜索结果: {len(found_skills)} 个skills found")

            if not found_skills:
                logger.info(f"未找到匹配的Skill: {skill_needed}")
                return None

            # Try to install the first matching skill
            first_skill = found_skills[0]
            logger.info(f"找到匹配的技能: {first_skill.name}，尝试自动安装...")

            install_result = await registry._skill_loader.install_skill(first_skill.name)

            if not install_result.get("success"):
                logger.info(f"安装失败: {install_result.get('error')}")
                return None

            logger.info(f"技能 {first_skill.name} 安装成功！正在重新加载工具...")

            # Reload dynamic tools to include the new skill
            try:
                dynamic_tools = await registry.load_dynamic_tools()
                if dynamic_tools:
                    logger.debug(f"重新加载了 {len(dynamic_tools)} 个动态工具")
            except Exception as e:
                logger.debug(f"重新加载动态工具失败: {e}")

            # Get updated tools description
            try:
                tools_description = registry.get_tools_description()
            except Exception as e:
                logger.debug(f"获取 tools_description 失败: {e}")
                tools_description = ""

            # Add a message to the LLM about the newly installed skill
            messages.append(
                provider_message.Message(
                    role="user",
                    content=f"""我已自动安装了技能「{first_skill.name}」！

技能描述: {first_skill.description}

请使用新安装的技能继续完成以下任务:
{task}

可用的工具:
{tools_description}

请继续执行任务。"""
                )
            )

            # Continue the ReAct loop - make another LLM call
            # This continues from where we left off in the execute_task method
            return await self._continue_execution(
                messages=messages,
                task=task,
                helper_plugin=helper_plugin,
                registry=registry,
                plugin=plugin,
                iteration_offset=0,
            )

        except Exception as e:
            logger.debug(f"Auto-install and retry failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _continue_execution(
        self,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        plugin,
        iteration_offset: int = 0,
    ) -> str:
        """
        Continue the ReAct execution loop after skill installation.
        This is a separate method that can be called to continue execution.
        """
        from langbot_plugin.api.entities.builtin.provider import message as provider_message

        # Get rate limit from config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))

        # Continue with remaining iterations (we've already done some)
        max_iterations = 5  # Continue with a few more iterations
        del iteration_offset  # Reserved for future use

        for iteration in range(max_iterations):
            # Check if task has been stopped
            if PlannerTool.is_task_stopped():
                logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                return "Task has been stopped by user."

            try:
                # Rate limiting
                current_time = time.time()
                time_since_last_call = current_time - PlannerTool._last_llm_call_time
                if time_since_last_call < rate_limit_seconds:
                    wait_time = rate_limit_seconds - time_since_last_call
                    logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before LLM call")
                    await asyncio.sleep(wait_time)
                    # Check if stopped during sleep
                    if PlannerTool.is_task_stopped():
                        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                        return "Task has been stopped by user."
                PlannerTool._last_llm_call_time = time.time()

                # Increment LLM call count
                PlannerTool._llm_call_count += 1
                logger.info(f"LLM 调用开始 (第 {PlannerTool._llm_call_count} 次), task: {task[:50]}... (skill安装后重试)")

                # Run LLM call with periodic stop check
                try:
                    async def call_llm_with_stop_check():
                        """Call LLM and periodically check for stop signal"""
                        llm_task = asyncio.create_task(plugin.invoke_llm(
                            llm_model_uuid=config.get('planner_model_uuid', ''),
                            messages=messages,
                            funcs=[]
                        ))

                        while not llm_task.done():
                            # Check both in-memory flag, user stop file, and run file
                            if PlannerTool.is_task_stopped() or SubprocessPlanner._check_user_stop_file():
                                llm_task.cancel()
                                raise asyncio.CancelledError("Task stopped during LLM call")
                            # Also check run file
                            if not os.path.exists(SubprocessPlanner._STOP_FILE):
                                llm_task.cancel()
                                raise asyncio.CancelledError("Run file deleted during LLM call")
                            await asyncio.sleep(0.05)

                        return await llm_task

                    response = await call_llm_with_stop_check()
                except asyncio.CancelledError:
                    PlannerTool.stop_task()
                    SubprocessPlanner._clear_user_stop_file()
                    logger.info("Task cancelled via CancelledError")
                    return "Task has been stopped by user."

                # Check if stopped after LLM call
                if PlannerTool.is_task_stopped():
                    logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                    return "Task has been stopped by user."

                # Check for DONE response
                if response.content and not response.tool_calls:
                    content_str = str(response.content)
                    if content_str.strip().upper().startswith("DONE:"):
                        result = content_str[5:].strip()
                        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                        return result

                    # Check for WORKING response
                    if content_str.strip().upper().startswith("WORKING:"):
                        working_msg = content_str[8:].strip()
                        logger.info(f"LLM 正在工作中: {working_msg}")
                        PlannerTool._invalid_response_count = 0
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=f"继续执行任务。{working_msg}"
                            )
                        )
                        continue

                    # Check for another NEED_SKILL (nested case)
                    if content_str.strip().upper().startswith("NEED_SKILL:"):
                        # Recursively try to install another skill
                        nested_skill_needed = content_str[11:].strip()
                        retry_result = await self._try_auto_install_and_retry(
                            nested_skill_needed, messages, task, helper_plugin, registry, plugin
                        )
                        if retry_result is not None:
                            return retry_result
                        # If nested install failed, continue with suggestion
                        return self._generate_skill_suggestion(nested_skill_needed)

                    # Try to parse and execute tool
                    tool_call = self._parse_tool_call_from_content(content_str)
                    if tool_call:
                        result = await self._execute_tool(tool_call, helper_plugin, registry)

                        if PlannerTool.is_task_stopped():
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task stopped by user. Last result:\n{result}"

                        # For JSON format responses (not tool_calls), send result as user message
                        # instead of tool_result to avoid Bedrock API tool_use_id mismatch error
                        hint = f"""
工具执行结果：{json.dumps(result)[:500]}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到最终答案 → 返回 DONE: 答案
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

关键：不要重复执行相同的工具！"""
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=hint
                            )
                        )
                        continue

                    # Invalid response
                    PlannerTool._invalid_response_count += 1
                    if PlannerTool._invalid_response_count >= 3:
                        return f"无法完成任务。LLM 连续返回了 {PlannerTool._invalid_response_count} 次无效响应。\n\n最后响应：\n{content_str[:500]}"
                    messages.append(response)
                    continue

                # Check if stopped before tool execution
                if PlannerTool.is_task_stopped():
                    logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                    return "Task has been stopped by user."

                # Handle structured tool calls
                if response.tool_calls:
                    for tool_call in response.tool_calls:
                        result = await self._execute_tool(tool_call, helper_plugin, registry)

                        if PlannerTool.is_task_stopped():
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return f"Task stopped by user. Last result:\n{result}"

                        messages.append(
                            provider_message.Message(
                                role="tool",
                                content=json.dumps(result),
                                tool_call_id=tool_call.id
                            )
                        )

                        # Add hint
                        hint = f"""
上一个工具执行结果：{json.dumps(result)[:500]}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到页面内容 → 立即返回 DONE: 总结内容
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

关键：不要重复执行相同的工具！"""
                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=hint
                            )
                        )
                        continue
                else:
                    if response.content:
                        content_str = str(response.content)
                        if content_str.strip().upper().startswith("DONE:"):
                            result = content_str[5:].strip()
                            logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                            return result
                        if content_str.strip().upper().startswith("WORKING:"):
                            working_msg = content_str[8:].strip()
                            logger.info(f"LLM 正在工作中: {working_msg}")
                            PlannerTool._invalid_response_count = 0
                            messages.append(
                                provider_message.Message(
                                    role="user",
                                    content=f"继续执行任务。{working_msg}"
                                )
                            )
                            continue

            except Exception as e:
                import traceback
                error_msg = str(e)
                logger.error(f"执行异常: {error_msg}")
                logger.error(traceback.format_exc())
                logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
                return f"Error during execution: {error_msg}"

        logger.info(f"LLM 调用结束，共调用 {PlannerTool._llm_call_count} 次")
        return f"Task reached maximum iterations ({max_iterations}) after skill installation."

    def _parse_tool_call_from_content(self, content: str):
        """Parse JSON tool call from LLM response content."""
        import re

        # First, try to parse the entire content as JSON directly
        try:
            data = json.loads(content)
            if isinstance(data, dict) and 'tool' in data and 'arguments' in data:
                tool_name = data['tool']
                arguments = data['arguments']
                class MockToolCall:
                    def __init__(self, name, args):
                        import uuid
                        self.id = f"call_{uuid.uuid4().hex[:8]}"
                        self.function = type('obj', (object,), {'name': name, 'arguments': args})()
                return MockToolCall(tool_name, arguments)
        except (json.JSONDecodeError, AttributeError):
            pass

        # Try to extract and parse JSON using regex that handles nested braces
        # Find the outermost JSON object
        json_match = re.search(r'\{[^{}]*"tool"[^{}]*\}[,}]', content)
        if json_match:
            # Find the full JSON including nested objects
            start = content.find('{', json_match.start())
            if start != -1:
                # Try to find matching closing brace
                depth = 0
                end = start
                for i, c in enumerate(content[start:], start):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                json_str = content[start:end]
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict) and 'tool' in data and 'arguments' in data:
                        tool_name = data['tool']
                        arguments = data['arguments']
                        class MockToolCall:
                            def __init__(self, name, args):
                                import uuid
                                self.id = f"call_{uuid.uuid4().hex[:8]}"
                                self.function = type('obj', (object,), {'name': name, 'arguments': args})()
                        return MockToolCall(tool_name, arguments)
                except json.JSONDecodeError:
                    pass

        # Fallback to regex parsing
        json_pattern = r'\{["\']tool["\']:\s*["\'](\w+)["\']\s*,\s*["\']arguments["\']:\s*\{[^}]*\}'
        match = re.search(json_pattern, content)
        if match:
            tool_name = match.group(1)
            try:
                start = content.find('{', match.start())
                depth = 0
                end = start
                for i, c in enumerate(content[start:], start):
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                json_str = content[start:end]
                data = json.loads(json_str)
                tool = data.get('tool', '')
                arguments = data.get('arguments', {})
                if tool and arguments:
                    class MockToolCall:
                        def __init__(self, name, args):
                            import uuid
                            self.id = f"call_{uuid.uuid4().hex[:8]}"
                            self.function = type('obj', (object,), {'name': name, 'arguments': args})()
                    return MockToolCall(tool, arguments)
            except (json.JSONDecodeError, KeyError):
                pass
        return None

    async def _execute_tool(
        self,
        tool_call,
        helper_plugin: 'LangTARS',
        registry: ToolRegistry | None = None,
    ) -> dict[str, Any]:
        """Execute a tool call and return the result."""
        tool_name = tool_call.function.name
        arguments = tool_call.function.arguments

        # Parse arguments if they're a string
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return {"error": f"Invalid arguments: {arguments}"}

        # Try to get tool from registry first
        tool = None
        if registry:
            tool = registry.get_tool(tool_name)
            if tool:
                logger.debug(f"Found tool '{tool_name}' in registry: {type(tool).__name__}")
            else:
                logger.debug(f"Tool '{tool_name}' not found in registry")

        # Execute the tool
        if isinstance(tool, BasePlannerTool):
            try:
                logger.debug(f"Executing tool '{tool_name}' with args: {arguments}")
                result = await tool.execute(helper_plugin, arguments)
                logger.debug(f"Tool result: {result}")
                return result
            except Exception as e:
                import traceback
                error_msg = f"Error executing tool {tool_name}: {str(e)}"
                logger.debug(error_msg)
                traceback.print_exc()
                return {"error": error_msg}

        # Fallback: execute built-in tools directly
        try:
            return await self._execute_builtin_tool(tool_name, arguments, helper_plugin)
        except Exception as e:
            return {"error": f"Unknown tool: {tool_name}, error: {str(e)}"}

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        helper_plugin: 'LangTARS',
    ) -> dict[str, Any]:
        """Execute built-in tools directly"""
        if tool_name == "shell":
            return await helper_plugin.run_shell(
                command=arguments.get('command', ''),
                timeout=arguments.get('timeout', 30)
            )
        elif tool_name == "read_file":
            return await helper_plugin.read_file(arguments.get('path', ''))
        elif tool_name == "write_file":
            return await helper_plugin.write_file(
                path=arguments.get('path', ''),
                content=arguments.get('content', '')
            )
        elif tool_name == "list_directory":
            return await helper_plugin.list_directory(
                path=arguments.get('path', '.'),
                show_hidden=arguments.get('show_hidden', False)
            )
        elif tool_name == "list_processes":
            return await helper_plugin.list_processes(
                filter_pattern=arguments.get('filter'),
                limit=arguments.get('limit', 20)
            )
        elif tool_name == "kill_process":
            return await helper_plugin.kill_process(
                target=arguments.get('target', ''),
                force=arguments.get('force', False)
            )
        elif tool_name == "open_app":
            target = arguments.get('target', '')
            is_url = target.startswith(('http://', 'https://', 'mailto:', 'tel:'))
            return await helper_plugin.open_app(
                app_name=None if is_url else target,
                url=target if is_url else None
            )
        elif tool_name == "close_app":
            return await helper_plugin.close_app(
                app_name=arguments.get('app_name', ''),
                force=arguments.get('force', False)
            )
        elif tool_name == "list_apps":
            return await helper_plugin.list_apps(limit=arguments.get('limit', 20))
        elif tool_name == "get_system_info":
            return await helper_plugin.get_system_info()
        elif tool_name == "search_files":
            return await helper_plugin.search_files(
                pattern=arguments.get('pattern', ''),
                path=arguments.get('path', '.')
            )
        elif tool_name == "ask_user":
            from components.tools.planner_tools.system import AskUserTool
            return await AskUserTool().execute(helper_plugin, arguments)
        elif tool_name == "fetch_url":
            url = arguments.get('url', '')
            if not url:
                return {"error": "URL is required"}
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        content = await response.text()
                        if len(content) > 10000:
                            content = content[:10000] + "\n... (truncated)"
                        return {
                            "success": True,
                            "url": url,
                            "status_code": response.status,
                            "content": content
                        }
            except Exception as e:
                return {"error": f"Failed to fetch URL: {str(e)}"}
        else:
            return {"error": f"Unknown tool: {tool_name}"}


# Streaming executor that yields after each iteration for interruptible execution
class PlannerExecutor:
    """Executor that runs planner with streaming for interrupt support"""

    async def execute_task_streaming(
        self,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin: 'LangTARSPlugin',
        helper_plugin: 'LangTARS' = None,
        registry: ToolRegistry | None = None,
        session=None,
        query_id: int = 0,
    ):
        """Execute task with streaming - yields after each iteration for interrupt check"""
        import asyncio

        # Register current task for cancellation support
        current_task = asyncio.current_task()
        PlannerTool.set_asyncio_task(current_task)

        # Reset state
        PlannerTool.reset_task_state()
        PlannerTool.set_current_task("default", task)

        if not task:
            yield "Error: No task provided."
            return

        if not llm_model_uuid:
            yield "Error: No LLM model specified."
            return

        # Tell user task started
        yield f"开始执行任务: {task[:50]}...\n"

        # Log task start
        logger.warning(f"=== 开始执行任务: {task[:50]}... (max_iterations={max_iterations}) ===")

        # Initialize registry if not provided
        if registry is None and plugin:
            registry = await self._get_tool_registry(plugin)

        # Get rate limit from config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))

        # Get tools description
        tools_description = ""
        if registry:
            try:
                tools_description = registry.get_tools_description()
            except Exception:
                pass

        # Build messages
        messages = [
            provider_message.Message(
                role="system",
                content=PlannerTool.SYSTEM_PROMPT
            ),
        ]

        user_message = f"{task}\n\nIMPORTANT: Use a tool to complete this task. Available tools:\n{tools_description}\n\nRemember: Respond with JSON format only: {{\"tool\": \"name\", \"arguments\": {{...}}}}"
        messages.append(provider_message.Message(
            role="user",
            content=user_message
        ))

        # 无效响应计数器，防止无限循环
        invalid_response_count = 0
        max_invalid_responses = 5  # 连续5次无效响应后终止

        # ReAct loop with streaming
        for iteration in range(max_iterations):
            # Yield control to event loop to allow other commands to be processed
            await asyncio.sleep(0)

            # Check if stopped (memory flag or user stop file)
            if PlannerTool.is_task_stopped():
                yield "Task stopped by user."
                return

            # Rate limiting
            current_time = time.time()
            time_since_last_call = current_time - PlannerTool._last_llm_call_time
            if time_since_last_call < rate_limit_seconds:
                await asyncio.sleep(rate_limit_seconds - time_since_last_call)
                if PlannerTool.is_task_stopped():
                    yield "Task stopped by user."
                    return
            PlannerTool._last_llm_call_time = time.time()

            PlannerTool._llm_call_count += 1
            logger.warning(f"[{iteration+1}/{max_iterations}] LLM 调用开始: {task[:30]}...")

            # Check stop before LLM call
            if PlannerTool.is_task_stopped():
                logger.warning("Stop detected BEFORE LLM call, stopping task")
                yield "Task stopped by user."
                return

            # Run LLM call with periodic stop check
            try:
                # Create a wrapper that checks stop during LLM call
                async def call_llm_with_stop_check():
                    """Call LLM and periodically check for stop signal"""
                    llm_task = asyncio.create_task(plugin.invoke_llm(
                        llm_model_uuid=llm_model_uuid,
                        messages=messages,
                        funcs=[]
                    ))

                    # Periodically check for stop while waiting for LLM
                    while not llm_task.done():
                        # Check both run file and user stop file
                        if not os.path.exists(SubprocessPlanner._STOP_FILE) or SubprocessPlanner._check_user_stop_file():
                            llm_task.cancel()
                            raise asyncio.CancelledError("Run file deleted during LLM call")
                        await asyncio.sleep(0.05)  # Check every 50ms - more responsive

                    return await llm_task

                response = await call_llm_with_stop_check()
            except asyncio.CancelledError:
                PlannerTool.stop_task()
                SubprocessPlanner._clear_user_stop_file()
                yield "Task stopped by user."
                return
            except Exception as e:
                logger.error(f"LLM call error: {e}")
                continue

            # Yield control to event loop after LLM call to allow stop check
            await asyncio.sleep(0)

            # 检查停止标志 - 在 LLM 调用完成后立即检查
            if PlannerTool.is_task_stopped():
                logger.warning("Stop detected AFTER LLM call, stopping task")
                yield "Task stopped by user."
                return

            # Log LLM response (full content including thinking)
            if response.content:
                content_str = str(response.content)
                logger.warning(f"[{iteration+1}] LLM 思考过程:\n{content_str[:1000]}")

                if response.content and not response.tool_calls:
                    content_str = str(response.content)
                    if content_str.strip().upper().startswith("DONE:"):
                        logger.warning(f"[{iteration+1}] 任务完成: {content_str[5:].strip()[:100]}")
                        yield content_str[5:].strip()
                        return

                    if content_str.strip().upper().startswith("WORKING:"):
                        logger.warning(f"[{iteration+1}] 工作中: {content_str[8:].strip()}")
                        invalid_response_count = 0  # 重置无效响应计数
                        messages.append(provider_message.Message(
                            role="user",
                            content=f"继续执行任务。{content_str[8:]}"
                        ))
                        continue

                    # Check if LLM indicates it needs a skill or encountered an error
                    if content_str.strip().upper().startswith("NEED_SKILL:"):
                        skill_needed = content_str[11:].strip()
                        logger.warning(f"[{iteration+1}] 需要技能或遇到错误: {skill_needed}")
                        # 如果是网络错误或无法完成的任务，直接返回结果
                        if any(keyword in skill_needed.lower() for keyword in ['无法连接', '网络', 'error', 'failed', '失败', '超时', 'timeout']):
                            logger.warning(f"[{iteration+1}] 检测到错误状态，任务结束")
                            yield f"任务无法完成: {skill_needed}"
                            return
                        # 否则提示用户需要安装技能
                        yield f"需要安装技能: {skill_needed}"
                        return

                    # Try parse JSON
                    tool_call = self._parse_tool_call_from_content(content_str)
                    if tool_call:
                        invalid_response_count = 0  # 重置无效响应计数
                        tool_name = tool_call.get('tool', 'unknown')
                        logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                        result = await self._execute_tool(
                            tool_call, helper_plugin or plugin, registry
                        )
                        logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")

                        # Yield control to allow stop command to be processed
                        await asyncio.sleep(0)

                        if PlannerTool.is_task_stopped():
                            yield "Task stopped by user."
                            return

                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=f"工具执行结果：{json.dumps(result)[:500]}\n\n请立即判断任务是否已完成：\n- 如果工具已成功执行 → 必须返回 DONE: 执行结果总结\n- 如果还需要获取页面内容 → 返回 WORKING: 需要做什么，然后调用获取内容的工具\n- 如果需要调用工具 → 返回 JSON 格式"
                            )
                        )
                        continue
                    else:
                        # 无法识别的响应格式，提示 LLM 重新格式化
                        invalid_response_count += 1
                        logger.warning(f"[{iteration+1}] 无法识别的响应格式 ({invalid_response_count}/{max_invalid_responses})，要求重新回复")
                        
                        # 如果连续多次无效响应，终止任务
                        if invalid_response_count >= max_invalid_responses:
                            logger.warning(f"[{iteration+1}] 连续 {max_invalid_responses} 次无效响应，任务终止")
                            yield f"任务无法完成: LLM 连续返回无效响应格式。最后的响应: {content_str[:200]}"
                            return
                        
                        messages.append(provider_message.Message(
                            role="user",
                            content=f"你的回复格式不正确。请严格按照以下格式之一回复：\n"
                                    f"1. 如果任务完成：DONE: 结果总结\n"
                                    f"2. 如果需要继续工作：WORKING: 下一步计划\n"
                                    f"3. 如果需要调用工具：{{\"tool\": \"工具名\", \"arguments\": {{...}}}}\n"
                                    f"4. 如果遇到错误无法继续：NEED_SKILL: 错误描述\n\n"
                                    f"你之前的回复是：{content_str[:200]}"
                        ))
                        continue

                # Handle tool_calls
                if response.tool_calls:
                    invalid_response_count = 0  # 重置无效响应计数
                    for tool_call in response.tool_calls:
                        tool_name = tool_call.function.name if hasattr(tool_call, 'function') else 'unknown'
                        logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                        result = await self._execute_tool(
                            tool_call, helper_plugin or plugin, registry
                        )
                        logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")

                        # Yield control to allow stop command to be processed
                        await asyncio.sleep(0)

                        if PlannerTool.is_task_stopped():
                            yield "Task stopped by user."
                            return

                        messages.append(
                            provider_message.Message(
                                role="tool",
                                content=json.dumps(result),
                                tool_call_id=tool_call.id
                            )
                        )

                        messages.append(
                            provider_message.Message(
                                role="user",
                                content=f"工具执行结果：{json.dumps(result)[:500]}\n\n请立即判断任务是否已完成：\n- 如果工具已成功执行 → 必须返回 DONE: 执行结果总结\n- 如果还需要获取页面内容 → 返回 WORKING: 需要做什么，然后调用获取内容的工具\n- 如果需要调用工具 → 返回 JSON 格式"
                            )
                        )

            # 如果响应既没有有效的 content 也没有 tool_calls，这是异常情况
            if not response.content and not response.tool_calls:
                invalid_response_count += 1
                logger.warning(f"[{iteration+1}] LLM 返回空响应 ({invalid_response_count}/{max_invalid_responses})，要求重新回复")
                
                # 如果连续多次空响应，终止任务
                if invalid_response_count >= max_invalid_responses:
                    logger.warning(f"[{iteration+1}] 连续 {max_invalid_responses} 次空响应，任务终止")
                    yield f"任务无法完成: LLM 连续返回空响应"
                    return
                
                messages.append(provider_message.Message(
                    role="user",
                    content="你的回复为空。请重新回复，按照以下格式之一：\n"
                            "1. 如果任务完成：DONE: 结果总结\n"
                            "2. 如果需要继续工作：WORKING: 下一步计划\n"
                            "3. 如果需要调用工具：{\"tool\": \"工具名\", \"arguments\": {...}}\n"
                            "4. 如果遇到错误无法继续：NEED_SKILL: 错误描述"
                ))

        yield f"Max iterations ({max_iterations}) reached. Task incomplete."

    async def _get_tool_registry(self, plugin, helper_plugin=None):
        """Get tool registry"""
        return await PlannerTool()._get_tool_registry(plugin)

    def _parse_tool_call_from_content(self, content: str):
        """Parse JSON tool call from content"""
        import re
        # First, try to parse the entire content as JSON directly
        try:
            data = json.loads(content)
            if isinstance(data, dict) and 'tool' in data and 'arguments' in data:
                return data
        except (json.JSONDecodeError, AttributeError):
            pass

        # Try regex for nested JSON
        json_match = re.search(r'\{[^{}]*"tool"[^{}]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        return None

    async def _execute_tool(self, tool_call, helper_plugin, registry):
        """Execute a tool call"""
        tool_name = None
        arguments = {}

        if hasattr(tool_call, 'function'):
            tool_name = tool_call.function.name
            arguments = tool_call.function.arguments
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except:
                    arguments = {}
        elif isinstance(tool_call, dict):
            tool_name = tool_call.get('tool') or tool_call.get('name')
            arguments = tool_call.get('arguments', {})

        if not tool_name:
            return {"error": "No tool name specified"}

        # Update background task status with current tool
        try:
            from components.commands.langtars import BackgroundTaskManager
            BackgroundTaskManager.set_task_status(
                task_description=PlannerTool._current_task_info.get("task_description", ""),
                step=f"正在执行工具: {tool_name}",
                tool=tool_name
            )
        except Exception as e:
            logger.debug(f"Failed to update task status: {e}")

        # Check if this is a dangerous operation that needs confirmation
        # 只有真正危险的命令才需要确认，普通命令如 cat, ls, echo 等不需要
        needs_confirmation = False
        
        # 只有特定的危险工具需要确认
        if tool_name in ['kill_process']:
            needs_confirmation = True
        
        # shell 命令只有包含危险模式时才需要确认
        if tool_name in ['shell', 'run_command'] and arguments.get('command', ''):
            cmd = arguments['command'].lower()
            # 真正危险的命令模式
            dangerous_patterns = [
                # 删除命令
                'rm -rf', 'rm -r', 'rm -f', 'rmdir', 'del /f', 'del /s', 'rd /s',
                # 磁盘操作
                'dd ', 'mkfs', 'format ', 'diskpart', 'fdisk',
                # 系统关键操作
                'reboot', 'shutdown', 'poweroff', 'halt', 'init 0', 'init 6',
                # 权限修改
                'chmod 777', 'chown', 'chgrp',
                # 危险重定向
                '> /dev/', '>/dev/',
                # Windows 危险命令
                'bcdedit', 'reg delete', 'taskkill /f',
            ]
            if any(p in cmd for p in dangerous_patterns):
                needs_confirmation = True
        
        # applescript 只有包含危险操作时才需要确认
        if tool_name == 'applescript' and arguments.get('script', ''):
            script = arguments['script'].lower()
            dangerous_patterns = ['do shell script "rm', 'do shell script "sudo', 'shutdown', 'reboot']
            if any(p in script for p in dangerous_patterns):
                needs_confirmation = True
        
        # delete_file 工具需要确认
        if tool_name in ['delete_file', 'rm']:
            needs_confirmation = True

        # If confirmation needed, wait for user response
        if needs_confirmation:
            try:
                from components.commands.langtars import BackgroundTaskManager
                
                # Build confirmation message
                confirm_msg = f"⚠️ 危险操作确认\n\n"
                confirm_msg += f"工具: {tool_name}\n"
                if tool_name == 'shell':
                    confirm_msg += f"命令: {arguments.get('command', '')}\n"
                elif tool_name == 'kill_process':
                    confirm_msg += f"目标: {arguments.get('target', '')}\n"
                elif tool_name == 'delete_file':
                    confirm_msg += f"文件: {arguments.get('path', '')}\n"
                confirm_msg += "\n请回复「!tars yes」确认执行，回复!tars no」取消，回复「!tars other」执行新命令。"
                
                # Send confirmation message to user
                try:
                    from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
                    # Try to get the plugin from helper_plugin
                    if hasattr(helper_plugin, 'plugin') and helper_plugin.plugin:
                        plugin_instance = helper_plugin.plugin
                    elif hasattr(helper_plugin, '_plugin'):
                        plugin_instance = helper_plugin._plugin
                    else:
                        plugin_instance = helper_plugin
                    
                    # Try to send confirmation message
                    sent = await BackgroundTaskManager.send_confirmation_message(confirm_msg, plugin_instance)
                    if sent:
                        logger.info("Confirmation message sent to user")
                except Exception as e:
                    logger.warning(f"Failed to send confirmation message: {e}")
                
                # Request confirmation
                BackgroundTaskManager._current_step = f"⏳ 等待确认: {tool_name}"
                confirmation_future = BackgroundTaskManager.request_confirmation(
                    tool_name=tool_name,
                    arguments=arguments,
                    message=confirm_msg
                )
                
                # Wait for confirmation with timeout (60 seconds)
                try:
                    confirmed = await asyncio.wait_for(confirmation_future, timeout=60.0)
                    
                    # Check if user provided a new instruction
                    from components.commands.langtars import BackgroundTaskManager
                    new_instruction = BackgroundTaskManager.get_user_new_instruction()
                    if new_instruction:
                        # Clear the instruction and return with new task
                        BackgroundTaskManager.clear_user_new_instruction()
                        return {
                            "success": False, 
                            "new_task": new_instruction,
                            "message": f"用户提供了新指令: {new_instruction}"
                        }
                    
                    if not confirmed:
                        return {"success": False, "error": "用户取消操作"}
                except asyncio.TimeoutError:
                    BackgroundTaskManager.confirm(False)  # Clear pending confirmation
                    return {"success": False, "error": "等待确认超时，操作已取消"}
                    
            except Exception as e:
                logger.warning(f"Confirmation error: {e}")
                # If confirmation fails, we'll proceed but log warning

        # Execute via registry
        try:
            if registry:
                tool = registry.get_tool(tool_name)
                if tool:
                    result = await tool.execute(helper_plugin, arguments)
                    return result
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}

        return {"error": f"Tool not found: {tool_name}"}


# Subprocess-based Planner Executor for parallel execution with stop support
class SubprocessPlanner:
    """Subprocess-based planner executor for parallel command execution"""

    # Use cross-platform temp directory
    _TEMP_DIR = tempfile.gettempdir()
    # PID file path for tracking subprocess
    _PID_FILE = os.path.join(_TEMP_DIR, "langtars_planner_pid")
    # Stop file - when this is deleted, the thread will stop
    _STOP_FILE = os.path.join(_TEMP_DIR, "langtars_planner_stop")
    # User stop file - user can create this file to stop the current task
    # Usage: touch /tmp/langtars_user_stop (or equivalent on Windows)
    _USER_STOP_FILE = os.path.join(_TEMP_DIR, "langtars_user_stop")

    # Process instance for true subprocess (not thread)
    _process: Any = None

    @classmethod
    def _check_user_stop_file(cls) -> bool:
        """Check if user created the stop file"""
        return os.path.exists(cls._USER_STOP_FILE)

    @classmethod
    def _clear_user_stop_file(cls) -> None:
        """Clear the user stop file after stopping"""
        try:
            if os.path.exists(cls._USER_STOP_FILE):
                os.remove(cls._USER_STOP_FILE)
        except Exception:
            pass

    @classmethod
    def _save_pid(cls, pid: int):
        """Save PID to file for cross-process tracking"""
        try:
            with open(cls._PID_FILE, 'w') as f:
                f.write(str(pid))
        except Exception as e:
            logger.error(f"Failed to save PID: {e}")

    @classmethod
    def _read_pid(cls) -> int | None:
        """Read PID from file"""
        try:
            if os.path.exists(cls._PID_FILE):
                with open(cls._PID_FILE, 'r') as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return None

    @classmethod
    def _clear_pid(cls):
        """Clear PID file"""
        try:
            if os.path.exists(cls._PID_FILE):
                os.remove(cls._PID_FILE)
        except Exception:
            pass

    @classmethod
    def _create_run_file(cls):
        """Create run file - existence means keep running"""
        try:
            with open(cls._STOP_FILE, 'w') as f:
                f.write("1")
            logger.debug(f"Created run file: {cls._STOP_FILE}")
        except Exception as e:
            logger.error(f"Failed to create run file {cls._STOP_FILE}: {e}")

    @classmethod
    def _remove_run_file(cls):
        """Remove run file - absence means stop"""
        try:
            if os.path.exists(cls._STOP_FILE):
                os.remove(cls._STOP_FILE)
        except Exception:
            pass

    @classmethod
    def _should_continue(cls) -> bool:
        """Check if should continue running - file exists means continue"""
        return os.path.exists(cls._STOP_FILE)

    @classmethod
    def is_running(cls) -> bool:
        """Check if a task is running (legacy, always returns False)"""
        # This method is kept for backwards compatibility
        return False


# True subprocess-based planner for actual process isolation
class TrueSubprocessPlanner:
    """
    True subprocess-based planner that runs in a separate process.
    This allows the stop command to directly kill the process.
    """

    _process: Any = None
    _pid: int | None = None
    _PID_FILE = "/tmp/langtars_subprocess_pid"

    @classmethod
    def is_running(cls) -> bool:
        """Check if a subprocess is running (using file-based PID tracking)"""
        # First check in-memory process
        if cls._process is not None and cls._process.poll() is None:
            return True

        # Fallback: check PID file
        try:
            if os.path.exists(cls._PID_FILE):
                with open(cls._PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process is alive
                try:
                    os.kill(pid, 0)  # Signal 0 just checks if process exists
                    return True
                except OSError:
                    # Process doesn't exist, clean up file
                    try:
                        os.remove(cls._PID_FILE)
                    except:
                        pass
        except Exception:
            pass

        return False

    @classmethod
    async def kill_process(cls) -> bool:
        """Kill the running subprocess directly"""
        import subprocess

        killed = False

        # Try to kill using in-memory process reference
        if cls._process is not None:
            try:
                if cls._process.poll() is None:  # Still running
                    cls._process.terminate()
                    try:
                        cls._process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        cls._process.kill()
                        cls._process.wait()
                    killed = True
            except Exception:
                pass
            cls._process = None

        # Also try to kill using PID from file
        pid_to_kill = cls._pid
        if pid_to_kill is None:
            # Try to read from PID file
            try:
                if os.path.exists(cls._PID_FILE):
                    with open(cls._PID_FILE, 'r') as f:
                        pid_to_kill = int(f.read().strip())
            except Exception:
                pass

        if pid_to_kill:
            try:
                os.kill(pid_to_kill, 9)
                killed = True
            except OSError:
                pass  # Process already dead

        # Clean up PID file
        try:
            if os.path.exists(cls._PID_FILE):
                os.remove(cls._PID_FILE)
        except Exception:
            pass

        cls._pid = None

        # Clear run file
        try:
            if os.path.exists(SubprocessPlanner._STOP_FILE):
                os.remove(SubprocessPlanner._STOP_FILE)
        except Exception:
            pass

        if killed:
            logger.warning("[TrueSubprocess] Process killed")
        else:
            logger.warning("[TrueSubprocess] No process to kill")

        return True

    @classmethod
    async def execute_in_subprocess(
        cls,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin,
        helper_plugin=None,
        registry=None,
        session=None,
        query_id: int = 0,
    ) -> AsyncGenerator[str, None]:
        """
        Execute planner in a true subprocess, yielding output in real-time.
        Returns an async generator that yields output strings.
        """
        import subprocess
        import base64
        import json
        import uuid
        import fcntl
        import select

        # Check if already running
        if cls.is_running():
            yield "⚠️ A task is already running. Use !tars stop to stop it first."
            return

        # Generate unique task ID
        task_id = str(uuid.uuid4())[:8]

        # Prepare arguments
        args = {
            "task": task,
            "max_iterations": max_iterations,
            "llm_model_uuid": llm_model_uuid,
            "config": plugin.get_config() if plugin else {},
            "task_id": task_id,
        }

        # Encode args as base64
        args_b64 = base64.b64encode(json.dumps(args).encode('utf-8')).decode('utf-8')

        # Get the path to this script
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "components", "tools", "planner_subprocess.py"
        )

        logger.warning(f"[TrueSubprocess] Starting subprocess: {script_path}")

        try:
            # Start subprocess with stderr captured for logger output
            cls._process = subprocess.Popen(
                ["python3", script_path, args_b64],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            cls._pid = cls._process.pid

            # Save PID for external tracking (use our own PID file)
            try:
                with open(cls._PID_FILE, 'w') as f:
                    f.write(str(cls._pid))
            except Exception:
                pass

            # Create run file to indicate task is running
            SubprocessPlanner._create_run_file()

            yield f"🚀 Task started (ID: {task_id}, PID: {cls._pid})\n\n"

            # Set stdout to non-blocking
            stdout_fd = cls._process.stdout.fileno()
            fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
            fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            # Also set stderr to non-blocking
            stderr_fd = cls._process.stderr.fileno()
            fl = fcntl.fcntl(stderr_fd, fcntl.F_GETFL)
            fcntl.fcntl(stderr_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            buffer = ""

            while True:
                # Check if process is still running
                if cls._process is None or cls._process.poll() is not None:
                    # Process has ended or was killed
                    break

                # Check if we should stop
                if PlannerTool.is_task_stopped():
                    logger.warning("[TrueSubprocess] Stop requested, killing process")
                    await cls.kill_process()
                    yield "\n🛑 Task stopped by user."
                    return

                # Check user stop file
                if SubprocessPlanner._check_user_stop_file():
                    SubprocessPlanner._clear_user_stop_file()
                    await cls.kill_process()
                    yield "\n🛑 Task stopped by user."
                    return

                # Read stdout with timeout
                try:
                    ready, _, _ = select.select([stdout_fd], [], [], 0.1)
                    if ready:
                        chunk = cls._process.stdout.read(4096)
                        if chunk:
                            buffer += chunk.decode('utf-8', errors='replace')
                            # Process complete lines
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                if line.strip():
                                    yield line + "\n"
                except Exception as e:
                    logger.debug(f"[TrueSubprocess] Read stdout error: {e}")

                # Also check stderr for any errors (logger output)
                try:
                    ready, _, _ = select.select([stderr_fd], [], [], 0)
                    if ready:
                        err_chunk = cls._process.stderr.read(4096)
                        if err_chunk:
                            err_text = err_chunk.decode('utf-8', errors='replace')
                            # Log stderr to our logger
                            for line in err_text.strip().split('\n'):
                                if line.strip():
                                    logger.debug(f"[Subprocess] {line}")
                except Exception:
                    pass

                # Yield control to event loop
                await asyncio.sleep(0.05)

            # Read any remaining output
            try:
                if cls._process is not None:
                    remaining = cls._process.stdout.read()
                    if remaining:
                        text = remaining.decode('utf-8', errors='replace')
                        for line in text.strip().split('\n'):
                            if line.strip():
                                yield line + "\n"
            except Exception:
                pass

            # Clean up
            if cls._process is not None:
                try:
                    cls._process.stdout.close()
                    cls._process.stderr.close()
                except Exception:
                    pass
                returncode = cls._process.returncode
            else:
                returncode = -1

            cls._process = None
            cls._pid = None

            # Clean up files
            SubprocessPlanner._clear_pid()
            SubprocessPlanner._remove_run_file()

            if returncode == 0 or PlannerTool.is_task_stopped():
                if PlannerTool.is_task_stopped():
                    yield "\n🛑 Task stopped by user."
                else:
                    yield "\n✅ Task completed."
            else:
                yield f"\n⚠️ Task exited with code {returncode}"

        except Exception as e:
            import traceback
            logger.error(f"[TrueSubprocess] Error: {e}")
            yield f"\n❌ Error: {str(e)}\n{traceback.format_exc()}"
            await cls.kill_process()
