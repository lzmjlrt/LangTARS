# ReAct executor for planner
# Core execution loop for autonomous task planning

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncGenerator, TYPE_CHECKING

from langbot_plugin.api.entities.builtin.provider import message as provider_message

from .state import get_state_manager, StateManager
from .parser import ResponseParser, ResponseType, get_parser
from .prompts import PromptManager
from .skill_manager import SkillManager, get_skill_manager
from .builtin_tools import (
    BuiltinToolExecutor,
    get_builtin_executor,
    needs_confirmation,
    build_confirmation_message,
)
from .subprocess_executor import SubprocessPlanner
from .plan_reviewer import get_plan_reviewer
from .memory import get_planner_memory
from .step_verifier import get_step_verifier

if TYPE_CHECKING:
    from components.tools.planner_tools.registry import ToolRegistry
    from components.tools.planner_tools import BasePlannerTool
    from main import LangTARS

logger = logging.getLogger(__name__)


def _extract_content_text(content) -> str:
    """Safely extract text from response.content which can be str, list[ContentElement], or None."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if hasattr(item, 'text') and item.text:
                parts.append(item.text)
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


class ReActExecutor:
    """
    ReAct (Reasoning and Acting) executor for autonomous task execution.
    Implements the core loop of: Think -> Act -> Observe -> Repeat.
    """
    
    def __init__(
        self,
        state_manager: StateManager | None = None,
        parser: ResponseParser | None = None,
        skill_manager: SkillManager | None = None,
        builtin_executor: BuiltinToolExecutor | None = None,
    ):
        """
        Initialize the ReAct executor.
        
        Args:
            state_manager: Task state manager
            parser: LLM response parser
            skill_manager: Skill installation manager
            builtin_executor: Built-in tool executor
        """
        self._state_manager = state_manager or get_state_manager()
        self._parser = parser or get_parser()
        self._skill_manager = skill_manager
        self._builtin_executor = builtin_executor or get_builtin_executor()
    
    async def execute(
        self,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin,
        helper_plugin: 'LangTARS' = None,
        registry: 'ToolRegistry | None' = None,
        session=None,
        query_id: int = 0,
    ) -> str:
        """
        Execute a task using the ReAct loop.
        
        Args:
            task: Task description
            max_iterations: Maximum number of iterations
            llm_model_uuid: UUID of the LLM model to use
            plugin: Plugin instance for LLM calls
            helper_plugin: Helper plugin for tool execution
            registry: Tool registry
            session: Session context
            query_id: Query ID
            
        Returns:
            Task result string
        """
        # Reset state for new task
        self._state_manager.reset()
        self._state_manager.create_task("default", task)
        
        if not task:
            return "Error: No task provided."
        
        if not llm_model_uuid:
            return "Error: No LLM model specified."
        
        # Initialize skill manager with registry
        if registry and not self._skill_manager:
            self._skill_manager = get_skill_manager(registry)
        elif registry and self._skill_manager:
            self._skill_manager.set_registry(registry)
        
        # Get config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))
        auto_cleanup = config.get('planner_auto_cleanup', True)
        
        # Set auto-cleanup preference in state manager
        self._state_manager.set_auto_cleanup(auto_cleanup)
        
        # Get tools in OpenAI format for native tool calling
        tools_openai_format = []
        if registry:
            try:
                tools_openai_format = registry.to_openai_format()
                logger.info(f"已加载 {len(tools_openai_format)} 个工具用于原生 tool calling")
            except Exception as e:
                logger.error(f"获取 tools_openai_format 失败: {e}")
        
        # Build initial messages
        messages = [
            provider_message.Message(
                role="system",
                content=PromptManager.get_system_prompt()
            ),
            provider_message.Message(
                role="user",
                content=PromptManager.get_task_prompt(task)
            ),
        ]
        
        # ReAct loop
        final_result = None
        for iteration in range(max_iterations):
            try:
                # Check if stopped
                if self._state_manager.is_stopped():
                    final_result = "Task has been stopped by user."
                    break
                
                # Rate limiting
                await self._apply_rate_limit(rate_limit_seconds)
                
                # Check if stopped after rate limit wait
                if self._state_manager.is_stopped():
                    self._log_llm_call_end()
                    final_result = "Task has been stopped by user."
                    break
                
                # Increment call count
                call_count = self._state_manager.increment_llm_call_count()
                logger.info(f"LLM 调用开始 (第 {call_count} 次), task: {task[:50]}...")
                
                # Call LLM with stop check and native tools
                try:
                    response = await self._call_llm_with_stop_check(
                        plugin, llm_model_uuid, messages, tools=tools_openai_format
                    )
                except asyncio.CancelledError:
                    self._state_manager.stop_current_task()
                    SubprocessPlanner.clear_user_stop_file()
                    logger.info("Task cancelled via CancelledError")
                    final_result = "Task has been stopped by user."
                    break
                
                # Check if stopped after LLM call
                if self._state_manager.is_stopped():
                    self._log_llm_call_end()
                    final_result = "Task has been stopped by user."
                    break
                
                # Process response
                result = await self._process_response(
                    response=response,
                    messages=messages,
                    task=task,
                    helper_plugin=helper_plugin or plugin,
                    registry=registry,
                    plugin=plugin,
                    iteration=iteration,
                    max_iterations=max_iterations,
                )
                
                if result is not None:
                    self._log_llm_call_end()
                    final_result = result
                    break
                
            except Exception as e:
                import traceback
                error_msg = str(e)
                logger.error(f"执行异常: {error_msg}")
                logger.error(traceback.format_exc())
                
                if "429" in error_msg or "rate limit" in error_msg.lower():
                    final_result = self._build_rate_limit_error(error_msg)
                    break
                
                self._log_llm_call_end()
                final_result = f"Error during execution: {error_msg}"
                break
        
        # If no result yet, we hit max iterations
        if final_result is None:
            self._log_llm_call_end()
            final_result = f"Task reached maximum iterations ({max_iterations}) without completion."
        
        # Cleanup resources after task completion
        try:
            cleanup_msg = await self._cleanup_resources(helper_plugin or plugin)
            if cleanup_msg:
                final_result = final_result + cleanup_msg
        except Exception as e:
            logger.warning(f"Error during resource cleanup: {e}")
        
        return final_result
    
    async def _apply_rate_limit(self, rate_limit_seconds: float) -> None:
        """Apply rate limiting between LLM calls"""
        current_time = time.time()
        last_call_time = self._state_manager.get_last_llm_call_time()
        time_since_last_call = current_time - last_call_time
        
        if time_since_last_call < rate_limit_seconds:
            wait_time = rate_limit_seconds - time_since_last_call
            logger.debug(f"Rate limiting: waiting {wait_time:.2f}s before LLM call")
            await asyncio.sleep(wait_time)
        
        self._state_manager.update_last_llm_call_time(time.time())
    
    async def _call_llm_with_stop_check(
        self,
        plugin,
        llm_model_uuid: str,
        messages: list,
        tools: list = None,
    ):
        """Call LLM and periodically check for stop signal
        
        Args:
            plugin: Plugin instance for LLM calls
            llm_model_uuid: UUID of the LLM model
            messages: Message history
            tools: List of tools in OpenAI format for native tool calling
        """
        llm_task = asyncio.create_task(plugin.invoke_llm(
            llm_model_uuid=llm_model_uuid,
            messages=messages,
            funcs=tools or []
        ))
        
        while not llm_task.done():
            # Check stop conditions
            if self._state_manager.is_stopped():
                llm_task.cancel()
                raise asyncio.CancelledError("Task stopped during LLM call")
            
            if SubprocessPlanner.check_user_stop_file():
                llm_task.cancel()
                raise asyncio.CancelledError("Task stopped during LLM call")
            
            if not SubprocessPlanner.should_continue():
                llm_task.cancel()
                raise asyncio.CancelledError("Run file deleted during LLM call")
            
            await asyncio.sleep(0.05)
        
        return await llm_task
    
    async def _process_response(
        self,
        response,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        plugin,
        iteration: int,
        max_iterations: int,
    ) -> str | None:
        """
        Process LLM response and return result if task is complete.
        
        Returns:
            Result string if task is complete, None to continue
        """
        # Handle content-based responses (no tool_calls)
        if response.content and not response.tool_calls:
            content_str = _extract_content_text(response.content)
            parsed = self._parser.parse(content_str)
            
            if parsed.type == ResponseType.DONE:
                return parsed.content
            
            if parsed.type == ResponseType.NEED_SKILL:
                return await self._handle_need_skill(
                    parsed.content, messages, task, helper_plugin, registry, plugin
                )
            
            if parsed.type == ResponseType.WORKING:
                logger.info(f"LLM 正在工作中: {parsed.content}")
                self._update_task_status(task, parsed.content, "")
                self._state_manager.reset_invalid_response_count()
                messages.append(provider_message.Message(
                    role="user",
                    content=PromptManager.get_continue_task_prompt(parsed.content)
                ))
                return None
            
            if parsed.type == ResponseType.TOOL_CALL and parsed.tool_call:
                return await self._handle_tool_call_from_content(
                    parsed.tool_call, messages, task, helper_plugin, registry,
                    iteration, max_iterations
                )
            
            # Invalid response
            return self._handle_invalid_response(content_str, messages)
        
        # Check if stopped before tool execution
        if self._state_manager.is_stopped():
            self._log_llm_call_end()
            return "Task has been stopped by user."
        
        # Handle structured tool calls
        if response.tool_calls:
            for tool_call in response.tool_calls:
                result = await self._execute_tool(tool_call, helper_plugin, registry)
                
                # Check for new task instruction
                if isinstance(result, dict) and result.get("new_task"):
                    new_task = result.get("new_task")
                    logger.info(f"用户提供了新任务: {new_task}")
                    return f"用户提供了新任务: {new_task}"
                
                # Check if stopped
                if self._state_manager.is_stopped():
                    self._log_llm_call_end()
                    return f"Task stopped by user. Last result:\n{result}"
                
                # Add tool result to messages
                messages.append(provider_message.Message(
                    role="tool",
                    content=json.dumps(result),
                    tool_call_id=tool_call.id
                ))
                
                # Add hint for next iteration
                messages.append(provider_message.Message(
                    role="user",
                    content=PromptManager.get_tool_result_hint_with_content(result, task)
                ))
                
                if iteration == max_iterations - 1:
                    self._log_llm_call_end()
                    return f"Task reached maximum iterations ({max_iterations}). Progress so far:\n{result}"
        else:
            # No tool calls and no valid content
            if response.content:
                content_str = _extract_content_text(response.content)
                is_done, result = self._parser.is_done_response(content_str)
                if is_done:
                    return result
                
                is_working, working_msg = self._parser.is_working_response(content_str)
                if is_working:
                    logger.info(f"LLM 正在工作中: {working_msg}")
                    self._state_manager.reset_invalid_response_count()
                    messages.append(provider_message.Message(
                        role="user",
                        content=PromptManager.get_continue_task_prompt(working_msg)
                    ))
                    return None
                
                is_need_skill, skill_needed = self._parser.is_need_skill_response(content_str)
                if is_need_skill:
                    return await self._handle_need_skill(
                        skill_needed, messages, task, helper_plugin, registry, plugin
                    )
        
        return None
    
    async def _handle_tool_call_from_content(
        self,
        tool_call,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        iteration: int,
        max_iterations: int,
    ) -> str | None:
        """Handle tool call parsed from content"""
        from .parser import MockToolCall
        
        # Create mock tool call for compatibility
        mock_call = MockToolCall(tool_call.name, tool_call.arguments)
        result = await self._execute_tool(mock_call, helper_plugin, registry)
        
        # Check for new task
        if isinstance(result, dict) and result.get("new_task"):
            new_task = result.get("new_task")
            logger.info(f"用户提供了新任务: {new_task}")
            return f"用户提供了新任务: {new_task}"
        
        # Check if stopped
        if self._state_manager.is_stopped():
            self._log_llm_call_end()
            return f"Task stopped by user. Last result:\n{result}"
        
        # Add result as user message (for JSON format responses)
        messages.append(provider_message.Message(
            role="user",
            content=PromptManager.get_tool_result_hint(result, task)
        ))
        
        if iteration == max_iterations - 1:
            self._log_llm_call_end()
            return f"Task reached maximum iterations ({max_iterations}). Progress so far:\n{result}"
        
        return None
    
    async def _handle_need_skill(
        self,
        skill_needed: str,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        plugin,
    ) -> str:
        """Handle NEED_SKILL response"""
        logger.info(f"需要技能: {skill_needed}")
        
        if self._skill_manager:
            # Try auto-install and retry
            async def continue_after_install(skill_name, skill_description, tools_description):
                messages.append(provider_message.Message(
                    role="user",
                    content=PromptManager.get_skill_installed_prompt(
                        skill_name, skill_description, task, tools_description
                    )
                ))
                # Continue execution with remaining iterations
                return await self._continue_execution(
                    messages, task, helper_plugin, registry, plugin
                )
            
            retry_result = await self._skill_manager.try_auto_install_and_retry(
                skill_needed, task, continue_after_install
            )
            
            if retry_result is not None:
                self._log_llm_call_end()
                return retry_result
            
            # Generate suggestion if auto-install failed
            self._log_llm_call_end()
            return self._skill_manager.generate_skill_suggestion(skill_needed)
        
        self._log_llm_call_end()
        return f"需要技能: {skill_needed}"
    
    def _handle_invalid_response(self, content: str, messages: list) -> str | None:
        """Handle invalid LLM response"""
        count = self._state_manager.increment_invalid_response_count()
        
        if count >= 3:
            logger.info(f"LLM 返回了 {count} 次无效响应，强制结束任务")
            return f"无法完成任务。LLM 连续返回了 {count} 次无效响应（未调用工具）。\n\n最后响应：\n{content[:500]}"
        
        # Add hint for retry
        messages.append(provider_message.Message(
            role="user",
            content=PromptManager.get_invalid_response_hint(content)
        ))
        return None
    
    async def _continue_execution(
        self,
        messages: list,
        task: str,
        helper_plugin,
        registry,
        plugin,
    ) -> str:
        """Continue execution after skill installation"""
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))
        max_iterations = 5
        
        # Get tools in OpenAI format for native tool calling
        tools_openai_format = []
        if registry:
            try:
                tools_openai_format = registry.to_openai_format()
            except Exception as e:
                logger.error(f"获取 tools_openai_format 失败: {e}")
        
        for iteration in range(max_iterations):
            if self._state_manager.is_stopped():
                self._log_llm_call_end()
                return "Task has been stopped by user."
            
            try:
                await self._apply_rate_limit(rate_limit_seconds)
                
                if self._state_manager.is_stopped():
                    self._log_llm_call_end()
                    return "Task has been stopped by user."
                
                call_count = self._state_manager.increment_llm_call_count()
                logger.info(f"LLM 调用开始 (第 {call_count} 次), task: {task[:50]}... (skill安装后重试)")
                
                try:
                    response = await self._call_llm_with_stop_check(
                        plugin,
                        config.get('planner_model_uuid', ''),
                        messages,
                        tools=tools_openai_format
                    )
                except asyncio.CancelledError:
                    self._state_manager.stop_current_task()
                    SubprocessPlanner.clear_user_stop_file()
                    return "Task has been stopped by user."
                
                if self._state_manager.is_stopped():
                    self._log_llm_call_end()
                    return "Task has been stopped by user."
                
                result = await self._process_response(
                    response=response,
                    messages=messages,
                    task=task,
                    helper_plugin=helper_plugin,
                    registry=registry,
                    plugin=plugin,
                    iteration=iteration,
                    max_iterations=max_iterations,
                )
                
                if result is not None:
                    return result
                
            except Exception as e:
                import traceback
                logger.error(f"执行异常: {e}")
                logger.error(traceback.format_exc())
                self._log_llm_call_end()
                return f"Error during execution: {e}"
        
        self._log_llm_call_end()
        return f"Task reached maximum iterations ({max_iterations}) after skill installation."
    
    async def _execute_tool(
        self,
        tool_call,
        helper_plugin,
        registry: 'ToolRegistry | None' = None,
    ) -> dict[str, Any]:
        """Execute a tool call"""
        tool_name = tool_call.function.name
        arguments = self._parser.parse_tool_arguments(tool_call.function.arguments)
        
        # Update task status
        self._update_task_status(
            self._state_manager.get_task_info().get("task_description", ""),
            f"正在执行工具: {tool_name}",
            tool_name
        )
        
        # Check if confirmation needed
        if needs_confirmation(tool_name, arguments):
            result = await self._request_confirmation(tool_name, arguments, helper_plugin)
            if result is not None:
                return result
        
        # Try registry first
        if registry:
            tool = registry.get_tool(tool_name)
            if tool:
                logger.debug(f"Found tool '{tool_name}' in registry")
                try:
                    result = await tool.execute(helper_plugin, arguments)
                    # Track opened resources for cleanup
                    self._track_resource_from_tool(tool_name, arguments, result)
                    return result
                except Exception as e:
                    import traceback
                    logger.debug(f"Error executing tool {tool_name}: {e}")
                    traceback.print_exc()
                    return {"error": f"Error executing tool {tool_name}: {str(e)}"}
        
        # Fallback to built-in tools
        try:
            result = await self._builtin_executor.execute(tool_name, arguments, helper_plugin)
            # Track opened resources for cleanup
            self._track_resource_from_tool(tool_name, arguments, result)
            return result
        except Exception as e:
            return {"error": f"Unknown tool: {tool_name}, error: {str(e)}"}
    
    def _track_resource_from_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any]
    ) -> None:
        """
        Track resources opened by tool execution for later cleanup.
        
        Args:
            tool_name: Name of the executed tool
            arguments: Tool arguments
            result: Tool execution result
        """
        # Skip if result indicates error
        if isinstance(result, dict) and result.get("error"):
            return
        
        # Track based on tool type
        if tool_name == "open_app":
            app_name = arguments.get("app_name") or arguments.get("target", "")
            if app_name and not app_name.startswith(("http://", "https://")):
                self._state_manager.track_opened_resource(
                    resource_type="app",
                    name=app_name,
                    metadata={"arguments": arguments}
                )
        
        elif tool_name in ("browser_navigate", "browser_new_tab"):
            url = arguments.get("url", "")
            if url:
                self._state_manager.track_opened_resource(
                    resource_type="browser_tab",
                    name=url,
                    metadata={"arguments": arguments}
                )
        
        elif tool_name in ("safari_open", "chrome_open", "edge_open"):
            url = arguments.get("url", "")
            browser_name = tool_name.replace("_open", "").title()
            self._state_manager.track_opened_resource(
                resource_type="browser",
                name=browser_name,
                metadata={"url": url, "arguments": arguments}
            )
        
        elif tool_name == "close_app":
            # Remove from tracking when app is closed
            app_name = arguments.get("app_name", "")
            if app_name:
                self._state_manager.remove_tracked_resource("app", app_name)
        
        elif tool_name == "browser_close_tab":
            # Note: We can't easily track which tab was closed without more context
            pass
    
    async def _request_confirmation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        helper_plugin,
    ) -> dict[str, Any] | None:
        """Request user confirmation for dangerous operations"""
        try:
            from components.commands.langtars import BackgroundTaskManager
            
            confirm_msg = build_confirmation_message(tool_name, arguments)
            
            # Try to send confirmation message
            try:
                from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain
                if hasattr(helper_plugin, 'plugin') and helper_plugin.plugin:
                    plugin_instance = helper_plugin.plugin
                elif hasattr(helper_plugin, '_plugin'):
                    plugin_instance = helper_plugin._plugin
                else:
                    plugin_instance = helper_plugin
                
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
            
            # Wait for confirmation
            try:
                confirmed = await asyncio.wait_for(confirmation_future, timeout=60.0)
                
                # Check for new instruction
                new_instruction = BackgroundTaskManager.get_user_new_instruction()
                if new_instruction:
                    BackgroundTaskManager.clear_user_new_instruction()
                    return {
                        "success": False,
                        "new_task": new_instruction,
                        "message": f"用户提供了新指令: {new_instruction}"
                    }
                
                if not confirmed:
                    return {"success": False, "error": "用户取消操作"}
                    
            except asyncio.TimeoutError:
                BackgroundTaskManager.confirm(False)
                return {"success": False, "error": "等待确认超时，操作已取消"}
                
        except Exception as e:
            logger.warning(f"Confirmation error: {e}")
        
        return None
    
    def _update_task_status(self, task_description: str, step: str, tool: str) -> None:
        """Update background task status"""
        try:
            from components.commands.langtars import BackgroundTaskManager
            BackgroundTaskManager.set_task_status(
                task_description=task_description,
                step=step,
                tool=tool
            )
        except Exception as e:
            logger.debug(f"Failed to update task status: {e}")
    
    def _log_llm_call_end(self) -> None:
        """Log LLM call end"""
        logger.info(f"LLM 调用结束，共调用 {self._state_manager.get_llm_call_count()} 次")
    
    def _build_rate_limit_error(self, error_msg: str) -> str:
        """Build rate limit error message"""
        return f"""错误: LLM API 请求过于频繁或余额不足。

请检查:
1. 账户是否有足够的余额
2. 是否开启了速率限制

可以稍后再试，或等待几秒钟后重试。

错误详情: {error_msg[:200]}"""
    
    async def _cleanup_resources(self, helper_plugin) -> str:
        """
        Clean up resources opened during task execution.
        
        Args:
            helper_plugin: Helper plugin for executing cleanup commands
            
        Returns:
            Cleanup summary message
        """
        resources = self._state_manager.get_resources_for_cleanup()
        if not resources:
            return ""
        
        cleanup_results = []
        logger.info(f"开始清理 {len(resources)} 个资源...")
        
        for resource in resources:
            try:
                if resource.resource_type == "app":
                    # Close application
                    result = await helper_plugin.close_app(
                        app_name=resource.name,
                        force=False
                    )
                    if result.get("success"):
                        cleanup_results.append(f"✅ 已关闭应用: {resource.name}")
                        logger.info(f"Closed app: {resource.name}")
                    else:
                        cleanup_results.append(f"⚠️ 关闭应用失败: {resource.name}")
                        logger.warning(f"Failed to close app: {resource.name}")
                
                elif resource.resource_type == "browser":
                    # Close browser
                    browser_name = resource.name.lower()
                    result = await helper_plugin.close_app(
                        app_name=browser_name,
                        force=False
                    )
                    if result.get("success"):
                        cleanup_results.append(f"✅ 已关闭浏览器: {resource.name}")
                        logger.info(f"Closed browser: {resource.name}")
                    else:
                        cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name}")
                        logger.warning(f"Failed to close browser: {resource.name}")
                
                elif resource.resource_type == "browser_tab":
                    # Close browser completely using browser_cleanup
                    try:
                        result = await helper_plugin.browser_cleanup()
                        if result.get("success"):
                            cleanup_results.append(f"✅ 已关闭浏览器: {resource.name[:50]}...")
                            logger.info(f"Closed browser via cleanup: {resource.name}")
                        else:
                            # Try close_tab as fallback
                            try:
                                result = await helper_plugin.browser_close_tab()
                                if result.get("success"):
                                    cleanup_results.append(f"✅ 已关闭浏览器标签页: {resource.name[:50]}...")
                                    logger.info(f"Closed browser tab: {resource.name}")
                                else:
                                    cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name[:50]}...")
                                    logger.warning(f"Failed to close browser: {resource.name}")
                            except Exception:
                                cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name[:50]}...")
                    except Exception as browser_error:
                        logger.warning(f"Error closing browser: {browser_error}")
                        cleanup_results.append(f"⚠️ 关闭浏览器失败: {str(browser_error)[:50]}")
                
            except Exception as e:
                logger.warning(f"Error cleaning up {resource.resource_type} {resource.name}: {e}")
                cleanup_results.append(f"❌ 清理失败 [{resource.resource_type}] {resource.name}: {str(e)}")
        
        # Clear tracked resources after cleanup
        self._state_manager.clear_tracked_resources()
        
        if cleanup_results:
            return "\n\n🧹 资源清理:\n" + "\n".join(cleanup_results)
        return ""


class PlannerExecutor:
    """
    Streaming executor that yields after each iteration for interruptible execution.
    Provides real-time output during task execution.
    """
    
    def __init__(self):
        self._state_manager = get_state_manager()
        self._parser = get_parser()
        self._builtin_executor = get_builtin_executor()
    
    async def execute_task_streaming(
        self,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin,
        helper_plugin=None,
        registry=None,
        session=None,
        query_id: int = 0,
    ) -> AsyncGenerator[str, None]:
        """Execute task with streaming - yields after each iteration"""
        # Register current task for cancellation
        current_task = asyncio.current_task()
        self._state_manager.set_asyncio_task(current_task)
        
        # Reset state
        self._state_manager.reset()
        self._state_manager.create_task("default", task)
        
        if not task:
            yield "Error: No task provided."
            return
        
        if not llm_model_uuid:
            yield "Error: No LLM model specified."
            return
        
        yield f"开始执行任务: {task[:50]}...\n"
        logger.warning(f"=== 开始执行任务: {task[:50]}... (max_iterations={max_iterations}) ===")

        # Get config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))
        auto_cleanup = config.get('planner_auto_cleanup', True)
        plan_review_enabled = config.get('planner_plan_review_enabled', True)
        memory_enabled = config.get('planner_memory_enabled', True)
        step_verify_enabled = config.get('planner_step_verify_enabled', True)

        # Set auto-cleanup preference in state manager
        self._state_manager.set_auto_cleanup(auto_cleanup)
        
        # Get tools in OpenAI format for native tool calling
        tools_openai_format = []
        if registry:
            try:
                tools_openai_format = registry.to_openai_format()
                logger.info(f"已加载 {len(tools_openai_format)} 个工具用于原生 tool calling")
            except Exception as e:
                logger.error(f"获取 tools_openai_format 失败: {e}")
        
        # Build messages
        messages = [
            provider_message.Message(
                role="system",
                content=PromptManager.get_system_prompt()
            ),
            provider_message.Message(
                role="user",
                content=PromptManager.get_task_prompt(task)
            ),
        ]

        # Inject relevant memories from previous tasks
        if memory_enabled:
            try:
                memory_dir = config.get('planner_memory_file', '') or None
                planner_memory = get_planner_memory(memory_dir)
                current_user_id = self._get_current_user_id(session)
                memories = planner_memory.get_relevant_memories(task, user_id=current_user_id)
                if memories:
                    memory_text = planner_memory.format_memories_for_prompt(memories)
                    messages.insert(1, provider_message.Message(
                        role="user",
                        content=PromptManager.get_memory_context(memory_text)
                    ))
                    logger.info(f"注入用户 {current_user_id} 的 {len(memories)} 条相关记忆")
            except Exception as e:
                logger.warning(f"记忆加载失败: {e}")

        invalid_response_count = 0
        max_invalid_responses = 5
        plan_regeneration_count = 0
        
        # ReAct loop
        for iteration in range(max_iterations):
            await asyncio.sleep(0)
            
            if self._state_manager.is_stopped():
                yield "Task stopped by user."
                return
            
            # Rate limiting
            current_time = time.time()
            last_call_time = self._state_manager.get_last_llm_call_time()
            if current_time - last_call_time < rate_limit_seconds:
                await asyncio.sleep(rate_limit_seconds - (current_time - last_call_time))
                if self._state_manager.is_stopped():
                    yield "Task stopped by user."
                    return
            self._state_manager.update_last_llm_call_time(time.time())
            
            call_count = self._state_manager.increment_llm_call_count()
            logger.warning(f"[{iteration+1}/{max_iterations}] LLM 调用开始: {task[:30]}...")
            
            if self._state_manager.is_stopped():
                logger.warning("Stop detected BEFORE LLM call")
                yield "Task stopped by user."
                return
            
            # Call LLM with native tools
            try:
                response = await self._call_llm_with_stop_check(plugin, llm_model_uuid, messages, tools=tools_openai_format)
            except asyncio.CancelledError:
                self._state_manager.stop_current_task()
                SubprocessPlanner.clear_user_stop_file()
                yield "Task stopped by user."
                return
            except Exception as e:
                logger.error(f"LLM call error: {e}")
                continue
            
            await asyncio.sleep(0)
            
            if self._state_manager.is_stopped():
                logger.warning("Stop detected AFTER LLM call")
                yield "Task stopped by user."
                return
            
            # Process response
            if response.content:
                content_str = _extract_content_text(response.content)
                logger.warning(f"[{iteration+1}] LLM 思考过程:\n{content_str[:1000]}")
                
                if not response.tool_calls:
                    parsed = self._parser.parse(content_str)
                    
                    if parsed.type == ResponseType.DONE:
                        logger.warning(f"[{iteration+1}] 任务完成: {parsed.content[:100]}")
                        # Save task memory
                        if memory_enabled:
                            try:
                                memory_dir = config.get('planner_memory_file', '') or None
                                planner_memory = get_planner_memory(memory_dir)
                                tools_used = self._extract_tools_used(messages)
                                current_user_id = self._get_current_user_id(session)
                                planner_memory.save_task_memory(task, parsed.content, tools_used, True, user_id=current_user_id)
                            except Exception as e:
                                logger.warning(f"保存记忆失败: {e}")
                        # Save conversation state for future continue
                        self._save_conversation_state(messages, task, registry, llm_model_uuid)
                        # Cleanup resources before returning
                        cleanup_msg = await self._cleanup_resources(helper_plugin or plugin)
                        if cleanup_msg:
                            yield parsed.content + cleanup_msg
                        else:
                            yield parsed.content
                        return
                    
                    # Handle PLAN response - set up plan steps
                    if parsed.type == ResponseType.PLAN:
                        if parsed.plan_steps:
                            # Plan review (规划审查)
                            if plan_review_enabled:
                                review_result = get_plan_reviewer().validate(parsed.plan_steps)
                                if not review_result.is_valid and plan_regeneration_count < 2:
                                    plan_regeneration_count += 1
                                    logger.warning(f"[{iteration+1}] 计划审查未通过 (第{plan_regeneration_count}次): {review_result.feedback}")
                                    yield f"\n⚠️ 计划审查未通过:\n{review_result.feedback}\n"
                                    messages.append(provider_message.Message(
                                        role="user",
                                        content=PromptManager.get_plan_review_feedback(review_result)
                                    ))
                                    invalid_response_count = 0
                                    continue
                                elif review_result.warnings:
                                    warnings_text = "\n".join(f"- {w}" for w in review_result.warnings)
                                    yield f"\n⚠️ 计划审查警告:\n{warnings_text}\n"

                            self._state_manager.set_plan_steps(parsed.plan_steps)
                            plan_display = self._state_manager.get_plan_display()
                            logger.warning(f"[{iteration+1}] 生成计划:\n{plan_display}")
                            # Send plan to user
                            yield f"\n{plan_display}\n"
                            # Update task status
                            self._update_task_status(task, "计划已生成，开始执行...", "")
                        invalid_response_count = 0
                        messages.append(provider_message.Message(
                            role="user",
                            content="计划已收到。请开始执行第一步，使用 STEP 1: 开始。"
                        ))
                        continue
                    
                    # Handle STEP response - starting a step
                    if parsed.type == ResponseType.STEP:
                        step_index = parsed.step_index
                        self._state_manager.start_step(step_index)
                        # Track message index for step verification
                        if step_verify_enabled:
                            self._state_manager.mark_step_start_message_index(len(messages))
                        plan_display = self._state_manager.get_plan_display()
                        logger.warning(f"[{iteration+1}] 开始步骤 {step_index}: {parsed.content}")
                        yield f"\n{plan_display}\n"
                        self._update_task_status(task, f"执行步骤 {step_index}: {parsed.content}", "")
                        invalid_response_count = 0
                        messages.append(provider_message.Message(
                            role="user",
                            content=f"好的，请继续执行步骤 {step_index}。"
                        ))
                        continue
                    
                    # Handle STEP_DONE response - step completed
                    if parsed.type == ResponseType.STEP_DONE:
                        step_index = parsed.step_index

                        # Step verification (执行复审)
                        if step_verify_enabled:
                            retry_count = self._state_manager.get_step_verify_retry_count(step_index)
                            if retry_count < 1:
                                start_idx = self._state_manager.get_step_start_message_index()
                                msgs_during = messages[start_idx:] if start_idx >= 0 else []
                                steps = self._state_manager.get_plan_steps()
                                step_desc = steps[step_index - 1].description if step_index <= len(steps) else ""
                                verification = get_step_verifier().verify(step_desc, parsed.content, msgs_during)
                                if not verification.is_valid:
                                    self._state_manager.increment_step_verify_retry(step_index)
                                    logger.warning(f"[{iteration+1}] 步骤 {step_index} 复审未通过: {verification.feedback}")
                                    yield f"\n⚠️ 步骤 {step_index} 复审未通过:\n{verification.feedback}\n"
                                    messages.append(provider_message.Message(
                                        role="user",
                                        content=PromptManager.get_step_verify_feedback(step_index, verification.feedback)
                                    ))
                                    invalid_response_count = 0
                                    continue

                        self._state_manager.complete_step(step_index, parsed.content)
                        plan_display = self._state_manager.get_plan_display()
                        logger.warning(f"[{iteration+1}] 步骤 {step_index} 完成: {parsed.content}")
                        yield f"\n{plan_display}\n"
                        
                        # Check if all steps are done
                        if self._state_manager.is_plan_complete():
                            # Save task memory
                            if memory_enabled:
                                try:
                                    memory_dir = config.get('planner_memory_file', '') or None
                                    planner_memory = get_planner_memory(memory_dir)
                                    tools_used = self._extract_tools_used(messages)
                                    current_user_id = self._get_current_user_id(session)
                                    planner_memory.save_task_memory(task, parsed.content, tools_used, True, user_id=current_user_id)
                                except Exception as e:
                                    logger.warning(f"保存记忆失败: {e}")
                            self._save_conversation_state(messages, task, registry, llm_model_uuid)
                            # Cleanup resources before returning
                            cleanup_msg = await self._cleanup_resources(helper_plugin or plugin)
                            yield f"\n✅ 所有步骤已完成！\n{plan_display}{cleanup_msg}"
                            return
                        
                        # Get next step
                        next_step = self._state_manager.get_next_pending_step()
                        if next_step > 0:
                            self._update_task_status(task, f"步骤 {step_index} 完成，准备执行步骤 {next_step}", "")
                            messages.append(provider_message.Message(
                                role="user",
                                content=f"步骤 {step_index} 已完成。请继续执行步骤 {next_step}。"
                            ))
                        else:
                            messages.append(provider_message.Message(
                                role="user",
                                content="所有步骤已完成，请返回 DONE: 总结任务结果。"
                            ))
                        invalid_response_count = 0
                        continue
                    
                    # Handle STEP_FAILED response - step failed
                    if parsed.type == ResponseType.STEP_FAILED:
                        step_index = parsed.step_index
                        self._state_manager.fail_step(step_index, parsed.content)
                        plan_display = self._state_manager.get_plan_display()
                        logger.warning(f"[{iteration+1}] 步骤 {step_index} 失败: {parsed.content}")
                        yield f"\n{plan_display}\n"
                        self._update_task_status(task, f"步骤 {step_index} 失败: {parsed.content}", "")
                        invalid_response_count = 0
                        messages.append(provider_message.Message(
                            role="user",
                            content=f"步骤 {step_index} 失败了。请决定是否继续执行其他步骤，或者返回 DONE: 说明失败原因。"
                        ))
                        continue
                    
                    # Handle STEP_SKIP response - step skipped
                    if parsed.type == ResponseType.STEP_SKIP:
                        step_index = parsed.step_index
                        self._state_manager.skip_step(step_index, parsed.content)
                        plan_display = self._state_manager.get_plan_display()
                        logger.warning(f"[{iteration+1}] 步骤 {step_index} 跳过: {parsed.content}")
                        yield f"\n{plan_display}\n"
                        
                        # Get next step
                        next_step = self._state_manager.get_next_pending_step()
                        if next_step > 0:
                            self._update_task_status(task, f"步骤 {step_index} 跳过，准备执行步骤 {next_step}", "")
                            messages.append(provider_message.Message(
                                role="user",
                                content=f"步骤 {step_index} 已跳过。请继续执行步骤 {next_step}。"
                            ))
                        else:
                            messages.append(provider_message.Message(
                                role="user",
                                content="所有步骤已处理完毕，请返回 DONE: 总结任务结果。"
                            ))
                        invalid_response_count = 0
                        continue
                    
                    if parsed.type == ResponseType.WORKING:
                        logger.warning(f"[{iteration+1}] 工作中: {parsed.content}")
                        invalid_response_count = 0
                        messages.append(provider_message.Message(
                            role="user",
                            content=PromptManager.get_continue_task_prompt(parsed.content)
                        ))
                        continue
                    
                    if parsed.type == ResponseType.NEED_SKILL:
                        skill_manager = get_skill_manager()
                        if skill_manager.is_error_state(parsed.content):
                            logger.warning(f"[{iteration+1}] 检测到错误状态")
                            yield f"任务无法完成: {parsed.content}"
                            return
                        yield f"需要安装技能: {parsed.content}"
                        return
                    
                    if parsed.type == ResponseType.TOOL_CALL and parsed.tool_call:
                        invalid_response_count = 0
                        tool_name = parsed.tool_call.name
                        logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                        
                        from .parser import MockToolCall
                        mock_call = MockToolCall(parsed.tool_call.name, parsed.tool_call.arguments)
                        result = await self._execute_tool(mock_call, helper_plugin or plugin, registry)
                        logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")
                        
                        await asyncio.sleep(0)
                        if self._state_manager.is_stopped():
                            yield "Task stopped by user."
                            return
                        
                        messages.append(provider_message.Message(
                            role="user",
                            content=PromptManager.get_streaming_tool_result_hint(result)
                        ))
                        continue
                    
                    # Invalid response
                    invalid_response_count += 1
                    logger.warning(f"[{iteration+1}] 无法识别的响应格式 ({invalid_response_count}/{max_invalid_responses})")
                    
                    if invalid_response_count >= max_invalid_responses:
                        yield f"任务无法完成: LLM 连续返回无效响应格式。最后的响应: {content_str[:200]}"
                        return
                    
                    messages.append(provider_message.Message(
                        role="user",
                        content=PromptManager.get_invalid_response_hint(content_str)
                    ))
                    continue
            
            # Handle tool_calls
            if response.tool_calls:
                invalid_response_count = 0
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name if hasattr(tool_call, 'function') else 'unknown'
                    logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                    
                    result = await self._execute_tool(tool_call, helper_plugin or plugin, registry)
                    logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")
                    
                    await asyncio.sleep(0)
                    if self._state_manager.is_stopped():
                        yield "Task stopped by user."
                        return
                    
                    messages.append(provider_message.Message(
                        role="tool",
                        content=json.dumps(result),
                        tool_call_id=tool_call.id
                    ))
                    messages.append(provider_message.Message(
                        role="user",
                        content=PromptManager.get_streaming_tool_result_hint(result)
                    ))
            
            # Empty response
            if not response.content and not response.tool_calls:
                invalid_response_count += 1
                logger.warning(f"[{iteration+1}] LLM 返回空响应 ({invalid_response_count}/{max_invalid_responses})")
                
                if invalid_response_count >= max_invalid_responses:
                    yield "任务无法完成: LLM 连续返回空响应"
                    return
                
                messages.append(provider_message.Message(
                    role="user",
                    content=PromptManager.get_empty_response_hint()
                ))
        
        # Save conversation state even if max iterations reached
        self._save_conversation_state(messages, task, registry, llm_model_uuid)
        # Cleanup resources before returning
        cleanup_msg = await self._cleanup_resources(helper_plugin or plugin)
        yield f"Max iterations ({max_iterations}) reached. Task incomplete.{cleanup_msg}"
    
    async def _call_llm_with_stop_check(self, plugin, llm_model_uuid: str, messages: list, tools: list = None):
        """Call LLM with periodic stop check
        
        Args:
            plugin: Plugin instance for LLM calls
            llm_model_uuid: UUID of the LLM model
            messages: Message history
            tools: List of tools in OpenAI format for native tool calling
        """
        llm_task = asyncio.create_task(plugin.invoke_llm(
            llm_model_uuid=llm_model_uuid,
            messages=messages,
            funcs=tools or []
        ))
        
        while not llm_task.done():
            if not SubprocessPlanner.should_continue() or SubprocessPlanner.check_user_stop_file():
                llm_task.cancel()
                raise asyncio.CancelledError("Run file deleted during LLM call")
            await asyncio.sleep(0.05)
        
        return await llm_task
    
    async def _execute_tool(self, tool_call, helper_plugin, registry) -> dict[str, Any]:
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
        
        # Update task status
        try:
            from components.commands.langtars import BackgroundTaskManager
            BackgroundTaskManager.set_task_status(
                task_description=self._state_manager.get_task_info().get("task_description", ""),
                step=f"正在执行工具: {tool_name}",
                tool=tool_name
            )
        except Exception:
            pass
        
        # Check confirmation
        if needs_confirmation(tool_name, arguments):
            result = await self._request_confirmation(tool_name, arguments, helper_plugin)
            if result is not None:
                return result
        
        # Execute via registry
        try:
            if registry:
                tool = registry.get_tool(tool_name)
                if tool:
                    result = await tool.execute(helper_plugin, arguments)
                    # Track opened resources for cleanup
                    self._track_resource_from_tool(tool_name, arguments, result)
                    return result
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}"}
        
        return {"error": f"Tool not found: {tool_name}"}
    
    def _track_resource_from_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any]
    ) -> None:
        """
        Track resources opened by tool execution for later cleanup.
        
        Args:
            tool_name: Name of the executed tool
            arguments: Tool arguments
            result: Tool execution result
        """
        # Skip if result indicates error
        if isinstance(result, dict) and result.get("error"):
            return
        
        # Track based on tool type
        if tool_name == "open_app":
            app_name = arguments.get("app_name") or arguments.get("target", "")
            if app_name and not app_name.startswith(("http://", "https://")):
                self._state_manager.track_opened_resource(
                    resource_type="app",
                    name=app_name,
                    metadata={"arguments": arguments}
                )
        
        elif tool_name in ("browser_navigate", "browser_new_tab"):
            url = arguments.get("url", "")
            if url:
                self._state_manager.track_opened_resource(
                    resource_type="browser_tab",
                    name=url,
                    metadata={"arguments": arguments}
                )
        
        elif tool_name in ("safari_open", "chrome_open", "edge_open"):
            url = arguments.get("url", "")
            browser_name = tool_name.replace("_open", "").title()
            self._state_manager.track_opened_resource(
                resource_type="browser",
                name=browser_name,
                metadata={"url": url, "arguments": arguments}
            )
        
        elif tool_name == "close_app":
            # Remove from tracking when app is closed
            app_name = arguments.get("app_name", "")
            if app_name:
                self._state_manager.remove_tracked_resource("app", app_name)
    
    async def _cleanup_resources(self, helper_plugin) -> str:
        """
        Clean up resources opened during task execution.
        
        Args:
            helper_plugin: Helper plugin for executing cleanup commands
            
        Returns:
            Cleanup summary message
        """
        resources = self._state_manager.get_resources_for_cleanup()
        if not resources:
            return ""
        
        cleanup_results = []
        logger.info(f"开始清理 {len(resources)} 个资源...")
        
        for resource in resources:
            try:
                if resource.resource_type == "app":
                    # Close application
                    result = await helper_plugin.close_app(
                        app_name=resource.name,
                        force=False
                    )
                    if result.get("success"):
                        cleanup_results.append(f"✅ 已关闭应用: {resource.name}")
                        logger.info(f"Closed app: {resource.name}")
                    else:
                        cleanup_results.append(f"⚠️ 关闭应用失败: {resource.name}")
                        logger.warning(f"Failed to close app: {resource.name}")
                
                elif resource.resource_type == "browser":
                    # Close browser
                    browser_name = resource.name.lower()
                    result = await helper_plugin.close_app(
                        app_name=browser_name,
                        force=False
                    )
                    if result.get("success"):
                        cleanup_results.append(f"✅ 已关闭浏览器: {resource.name}")
                        logger.info(f"Closed browser: {resource.name}")
                    else:
                        cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name}")
                        logger.warning(f"Failed to close browser: {resource.name}")
                
                elif resource.resource_type == "browser_tab":
                    # Close browser completely using browser_cleanup
                    try:
                        result = await helper_plugin.browser_cleanup()
                        if result.get("success"):
                            cleanup_results.append(f"✅ 已关闭浏览器: {resource.name[:50]}...")
                            logger.info(f"Closed browser via cleanup: {resource.name}")
                        else:
                            # Try close_tab as fallback
                            try:
                                result = await helper_plugin.browser_close_tab()
                                if result.get("success"):
                                    cleanup_results.append(f"✅ 已关闭浏览器标签页: {resource.name[:50]}...")
                                    logger.info(f"Closed browser tab: {resource.name}")
                                else:
                                    cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name[:50]}...")
                                    logger.warning(f"Failed to close browser: {resource.name}")
                            except Exception:
                                cleanup_results.append(f"⚠️ 关闭浏览器失败: {resource.name[:50]}...")
                    except Exception as browser_error:
                        logger.warning(f"Error closing browser: {browser_error}")
                        cleanup_results.append(f"⚠️ 关闭浏览器失败: {str(browser_error)[:50]}")
                
            except Exception as e:
                logger.warning(f"Error cleaning up {resource.resource_type} {resource.name}: {e}")
                cleanup_results.append(f"❌ 清理失败 [{resource.resource_type}] {resource.name}: {str(e)}")
        
        # Clear tracked resources after cleanup
        self._state_manager.clear_tracked_resources()
        
        if cleanup_results:
            return "\n\n🧹 资源清理:\n" + "\n".join(cleanup_results)
        return ""
    
    async def _request_confirmation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        helper_plugin,
    ) -> dict[str, Any] | None:
        """Request user confirmation"""
        try:
            from components.commands.langtars import BackgroundTaskManager
            
            confirm_msg = build_confirmation_message(tool_name, arguments)
            
            try:
                if hasattr(helper_plugin, 'plugin') and helper_plugin.plugin:
                    plugin_instance = helper_plugin.plugin
                elif hasattr(helper_plugin, '_plugin'):
                    plugin_instance = helper_plugin._plugin
                else:
                    plugin_instance = helper_plugin
                
                await BackgroundTaskManager.send_confirmation_message(confirm_msg, plugin_instance)
            except Exception as e:
                logger.warning(f"Failed to send confirmation: {e}")
            
            BackgroundTaskManager._current_step = f"⏳ 等待确认: {tool_name}"
            confirmation_future = BackgroundTaskManager.request_confirmation(
                tool_name=tool_name,
                arguments=arguments,
                message=confirm_msg
            )
            
            try:
                confirmed = await asyncio.wait_for(confirmation_future, timeout=60.0)
                
                new_instruction = BackgroundTaskManager.get_user_new_instruction()
                if new_instruction:
                    BackgroundTaskManager.clear_user_new_instruction()
                    return {
                        "success": False,
                        "new_task": new_instruction,
                        "message": f"用户提供了新指令: {new_instruction}"
                    }
                
                if not confirmed:
                    return {"success": False, "error": "用户取消操作"}
                    
            except asyncio.TimeoutError:
                BackgroundTaskManager.confirm(False)
                return {"success": False, "error": "等待确认超时，操作已取消"}
                
        except Exception as e:
            logger.warning(f"Confirmation error: {e}")
        
        return None
    
    async def _get_tool_registry(self, plugin, helper_plugin=None):
        """Get tool registry"""
        from .tool import PlannerTool
        return await PlannerTool()._get_tool_registry(plugin)

    async def execute_task_streaming_with_messages(
        self,
        messages: list,
        task: str,
        original_task: str | None,
        max_iterations: int,
        llm_model_uuid: str,
        plugin,
        helper_plugin=None,
        registry=None,
        session=None,
        query_id: int = 0,
    ) -> AsyncGenerator[str, None]:
        """Execute task with pre-existing messages - for continue functionality.
        
        This method allows continuing a conversation with existing message history.
        """
        # Register current task for cancellation
        current_task = asyncio.current_task()
        self._state_manager.set_asyncio_task(current_task)
        
        # Reset state but keep messages
        self._state_manager.reset()
        self._state_manager.create_task("continue", task)
        
        if not messages:
            yield "Error: No messages provided."
            return
        
        if not llm_model_uuid:
            yield "Error: No LLM model specified."
            return
        
        yield f"继续执行任务: {task[:50]}...\n"
        logger.warning(f"=== 继续执行任务: {task[:50]}... (max_iterations={max_iterations}) ===")
        
        # Get config
        config = plugin.get_config() if plugin else {}
        rate_limit_seconds = float(config.get('planner_rate_limit_seconds', 1))
        plan_review_enabled = config.get('planner_plan_review_enabled', True)
        memory_enabled = config.get('planner_memory_enabled', True)
        step_verify_enabled = config.get('planner_step_verify_enabled', True)

        # Get tools in OpenAI format for native tool calling
        tools_openai_format = []
        if registry:
            try:
                tools_openai_format = registry.to_openai_format()
            except Exception as e:
                logger.error(f"获取 tools_openai_format 失败: {e}")

        invalid_response_count = 0
        max_invalid_responses = 5
        plan_regeneration_count = 0
        
        # ReAct loop
        for iteration in range(max_iterations):
            await asyncio.sleep(0)
            
            if self._state_manager.is_stopped():
                yield "Task stopped by user."
                return
            
            # Rate limiting
            current_time = time.time()
            last_call_time = self._state_manager.get_last_llm_call_time()
            if current_time - last_call_time < rate_limit_seconds:
                await asyncio.sleep(rate_limit_seconds - (current_time - last_call_time))
                if self._state_manager.is_stopped():
                    yield "Task stopped by user."
                    return
            self._state_manager.update_last_llm_call_time(time.time())
            
            call_count = self._state_manager.increment_llm_call_count()
            logger.warning(f"[{iteration+1}/{max_iterations}] LLM 调用开始 (继续): {task[:30]}...")
            
            if self._state_manager.is_stopped():
                logger.warning("Stop detected BEFORE LLM call")
                yield "Task stopped by user."
                return
            
            # Call LLM with native tools
            try:
                response = await self._call_llm_with_stop_check(plugin, llm_model_uuid, messages, tools=tools_openai_format)
            except asyncio.CancelledError:
                self._state_manager.stop_current_task()
                SubprocessPlanner.clear_user_stop_file()
                yield "Task stopped by user."
                return
            except Exception as e:
                logger.error(f"LLM call error: {e}")
                continue
            
            await asyncio.sleep(0)
            
            if self._state_manager.is_stopped():
                logger.warning("Stop detected AFTER LLM call")
                yield "Task stopped by user."
                return
            
            # Process response (same logic as execute_task_streaming)
            if response.content:
                content_str = _extract_content_text(response.content)
                logger.warning(f"[{iteration+1}] LLM 思考过程:\n{content_str[:1000]}")
                
                if not response.tool_calls:
                    parsed = self._parser.parse(content_str)
                    
                    if parsed.type == ResponseType.DONE:
                        logger.warning(f"[{iteration+1}] 任务完成: {parsed.content[:100]}")
                        # Save conversation state for future continue
                        self._save_conversation_state(messages, task, registry, llm_model_uuid)
                        yield parsed.content
                        return
                    
                    if parsed.type == ResponseType.WORKING:
                        logger.warning(f"[{iteration+1}] 工作中: {parsed.content}")
                        invalid_response_count = 0
                        messages.append(provider_message.Message(
                            role="user",
                            content=PromptManager.get_continue_task_prompt(parsed.content)
                        ))
                        continue
                    
                    if parsed.type == ResponseType.NEED_SKILL:
                        skill_manager = get_skill_manager()
                        if skill_manager.is_error_state(parsed.content):
                            logger.warning(f"[{iteration+1}] 检测到错误状态")
                            yield f"任务无法完成: {parsed.content}"
                            return
                        yield f"需要安装技能: {parsed.content}"
                        return
                    
                    if parsed.type == ResponseType.TOOL_CALL and parsed.tool_call:
                        invalid_response_count = 0
                        tool_name = parsed.tool_call.name
                        logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                        
                        from .parser import MockToolCall
                        mock_call = MockToolCall(parsed.tool_call.name, parsed.tool_call.arguments)
                        result = await self._execute_tool(mock_call, helper_plugin or plugin, registry)
                        logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")
                        
                        await asyncio.sleep(0)
                        if self._state_manager.is_stopped():
                            yield "Task stopped by user."
                            return
                        
                        messages.append(provider_message.Message(
                            role="user",
                            content=PromptManager.get_streaming_tool_result_hint(result)
                        ))
                        continue
                    
                    # Invalid response
                    invalid_response_count += 1
                    logger.warning(f"[{iteration+1}] 无法识别的响应格式 ({invalid_response_count}/{max_invalid_responses})")
                    
                    if invalid_response_count >= max_invalid_responses:
                        yield f"任务无法完成: LLM 连续返回无效响应格式。最后的响应: {content_str[:200]}"
                        return
                    
                    messages.append(provider_message.Message(
                        role="user",
                        content=PromptManager.get_invalid_response_hint(content_str)
                    ))
                    continue
            
            # Handle tool_calls
            if response.tool_calls:
                invalid_response_count = 0
                for tool_call in response.tool_calls:
                    tool_name = tool_call.function.name if hasattr(tool_call, 'function') else 'unknown'
                    logger.warning(f"[{iteration+1}] 调用工具: {tool_name}")
                    
                    result = await self._execute_tool(tool_call, helper_plugin or plugin, registry)
                    logger.warning(f"[{iteration+1}] 工具结果: {str(result)[:100]}")
                    
                    await asyncio.sleep(0)
                    if self._state_manager.is_stopped():
                        yield "Task stopped by user."
                        return
                    
                    messages.append(provider_message.Message(
                        role="tool",
                        content=json.dumps(result),
                        tool_call_id=tool_call.id
                    ))
                    messages.append(provider_message.Message(
                        role="user",
                        content=PromptManager.get_streaming_tool_result_hint(result)
                    ))
            
            # Empty response
            if not response.content and not response.tool_calls:
                invalid_response_count += 1
                logger.warning(f"[{iteration+1}] LLM 返回空响应 ({invalid_response_count}/{max_invalid_responses})")
                
                if invalid_response_count >= max_invalid_responses:
                    yield "任务无法完成: LLM 连续返回空响应"
                    return
                
                messages.append(provider_message.Message(
                    role="user",
                    content=PromptManager.get_empty_response_hint()
                ))
        
        # Save conversation state even if max iterations reached
        self._save_conversation_state(messages, task, registry, llm_model_uuid)
        yield f"Max iterations ({max_iterations}) reached. Task incomplete."

    def _save_conversation_state(
        self,
        messages: list,
        task: str,
        registry,
        llm_model_uuid: str
    ) -> None:
        """Save conversation state for continue functionality."""
        try:
            from components.commands.langtars import BackgroundTaskManager
            BackgroundTaskManager.save_conversation_state(
                messages=messages,
                task=task,
                registry=registry,
                llm_model_uuid=llm_model_uuid
            )
            logger.info(f"Saved conversation state with {len(messages)} messages")
        except Exception as e:
            logger.warning(f"Failed to save conversation state: {e}")

    def _update_task_status(self, task_description: str, step: str, tool: str) -> None:
        """Update background task status"""
        try:
            from components.commands.langtars import BackgroundTaskManager
            BackgroundTaskManager.set_task_status(
                task_description=task_description,
                step=step,
                tool=tool
            )
        except Exception as e:
            logger.debug(f"Failed to update task status: {e}")

    @staticmethod
    def _extract_tools_used(messages: list) -> list[str]:
        """Extract unique tool names from message history"""
        tools = set()
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tc in msg.tool_calls:
                    if hasattr(tc, 'function') and hasattr(tc.function, 'name'):
                        tools.add(tc.function.name)
            if hasattr(msg, 'role') and msg.role == 'tool' and hasattr(msg, 'content'):
                try:
                    data = json.loads(str(msg.content))
                    if isinstance(data, dict) and 'tool' in data:
                        tools.add(data['tool'])
                except (json.JSONDecodeError, ValueError):
                    pass
        return list(tools)

    @staticmethod
    def _get_current_user_id(session=None) -> str:
        """Get the current user ID from session or BackgroundTaskManager"""
        if session and hasattr(session, 'launcher_id') and session.launcher_id:
            return str(session.launcher_id)
        try:
            from components.commands.langtars import BackgroundTaskManager
            uid = BackgroundTaskManager.get_current_user()
            if uid:
                return uid
        except Exception:
            pass
        return "default"
