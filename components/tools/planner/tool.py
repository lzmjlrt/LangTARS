# PlannerTool - Entry point for planner functionality
# Provides the Tool interface for the planner

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from components.helpers.logging_setup import setup_langtars_file_logging

# Ensure logging is set up
setup_langtars_file_logging()
logger = logging.getLogger(__name__)

from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.entities.builtin.provider import session as provider_session

from .state import get_state_manager, StateManager
from .executor import ReActExecutor
from .prompts import PromptManager
from .subprocess_executor import SubprocessPlanner

if TYPE_CHECKING:
    from components.tools.planner_tools.registry import ToolRegistry


class PlannerTool(Tool):
    """
    Planner tool - ReAct loop for autonomous task execution.
    This is the main entry point for the planner functionality.
    """
    
    __kind__ = "Tool"
    
    # Tool registry instance (class-level for sharing)
    _tool_registry: 'ToolRegistry | None' = None
    
    # System prompt (exposed for compatibility)
    SYSTEM_PROMPT = PromptManager.SYSTEM_PROMPT
    
    def __init__(self):
        self._state_manager = get_state_manager()
        self._executor = ReActExecutor(state_manager=self._state_manager)
    
    # Class methods for external control
    
    @classmethod
    def stop_task(cls, task_id: str = "default") -> bool:
        """Stop the current running task"""
        state_manager = get_state_manager()
        return state_manager.stop_current_task()
    
    @classmethod
    def is_task_stopped(cls) -> bool:
        """Check if the current task has been stopped"""
        state_manager = get_state_manager()
        return state_manager.is_stopped()
    
    @classmethod
    def reset_task_state(cls) -> None:
        """Reset task state for a new task"""
        state_manager = get_state_manager()
        state_manager.reset()
    
    @classmethod
    def set_current_task(cls, task_id: str, task_description: str) -> None:
        """Set the current running task info"""
        state_manager = get_state_manager()
        state_manager.create_task(task_id, task_description)
    
    @classmethod
    def get_current_task(cls) -> dict:
        """Get the current running task info"""
        state_manager = get_state_manager()
        return state_manager.get_task_info()
    
    @classmethod
    def set_asyncio_task(cls, task: Any) -> None:
        """Set the current asyncio task for cancellation support"""
        state_manager = get_state_manager()
        state_manager.set_asyncio_task(task)
    
    async def _get_tool_registry(self, plugin=None) -> 'ToolRegistry':
        """Get or create the tool registry"""
        if PlannerTool._tool_registry is None:
            from components.tools.planner_tools.registry import ToolRegistry
            p = plugin if plugin else getattr(self, 'plugin', None)
            if p:
                PlannerTool._tool_registry = ToolRegistry(p)
                await PlannerTool._tool_registry.initialize()
        return PlannerTool._tool_registry
    
    async def call(
        self,
        params: dict[str, Any],
        session: provider_session.Session,
        query_id: int,
    ) -> str:
        """
        Execute the planner to complete a task using ReAct loop.
        
        Args:
            params: Parameters including 'task', 'max_iterations', 'llm_model_uuid'
            session: Session context
            query_id: Query ID
            
        Returns:
            Task result string
        """
        task = params.get('task', '')
        max_iterations = params.get('max_iterations', 5)
        llm_model_uuid = params.get('llm_model_uuid', '')
        
        if not task:
            return "Error: No task provided. Please specify a task to execute."
        
        # Get plugin instance
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
        plugin,
        helper_plugin=None,
        registry: 'ToolRegistry | None' = None,
        session=None,
        query_id: int = 0,
    ) -> str:
        """
        Execute task with ReAct loop using provided plugin instance.
        
        Args:
            task: Task description
            max_iterations: Maximum iterations
            llm_model_uuid: LLM model UUID
            plugin: Plugin instance
            helper_plugin: Helper plugin for tool execution
            registry: Tool registry
            session: Session context
            query_id: Query ID
            
        Returns:
            Task result string
        """
        # Initialize registry if not provided
        if registry is None and plugin:
            registry = await self._get_tool_registry(plugin)
        
        return await self._executor.execute(
            task=task,
            max_iterations=max_iterations,
            llm_model_uuid=llm_model_uuid,
            plugin=plugin,
            helper_plugin=helper_plugin,
            registry=registry,
            session=session,
            query_id=query_id,
        )


# Backwards compatibility aliases
# These ensure existing code continues to work

def _get_planner_tool_class_var(name: str):
    """Get class variable from PlannerTool for backwards compatibility"""
    state_manager = get_state_manager()
    
    if name == '_task_stopped':
        return state_manager.is_stopped()
    elif name == '_llm_call_count':
        return state_manager.get_llm_call_count()
    elif name == '_invalid_response_count':
        return state_manager.get_invalid_response_count()
    elif name == '_current_task_info':
        return state_manager.get_task_info()
    elif name == '_last_llm_call_time':
        return state_manager.get_last_llm_call_time()
    
    return None


# Add class-level property access for backwards compatibility
PlannerTool._task_stopped = property(lambda self: get_state_manager().is_stopped())
PlannerTool._llm_call_count = property(lambda self: get_state_manager().get_llm_call_count())
