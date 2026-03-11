# Tool registry for planner
# Central registry for all available tools

from __future__ import annotations

import platform
from typing import Any

from . import BasePlannerTool
from .system import (
    ShellTool,
    ListProcessesTool,
    KillProcessTool,
    OpenAppTool,
    CloseAppTool,
    ListAppsTool,
    GetSystemInfoTool,
    AskUserTool,
    AppleScriptTool,
    PowerShellTool,
    WindowsSendKeysTool,
    WindowsFocusWindowTool,
    WindowsScreenshotTool,
)
from .file import (
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    SearchFilesTool,
)
from .network import FetchURLTool
from .browser import (
    BrowserNavigateTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserScreenshotTool,
    BrowserGetContentTool,
    BrowserWaitTool,
    BrowserScrollTool,
    BrowserExecuteScriptTool,
    BrowserNewTabTool,
    BrowserCloseTabTool,
    BrowserGetUrlTool,
    BrowserReloadTool,
    BrowserPressKeyTool,
    BrowserSelectOptionTool,
    BrowserGetAttributeTool,
    # Safari tools
    SafariOpenTool,
    SafariNavigateTool,
    SafariGetContentTool,
    SafariClickTool,
    SafariTypeTool,
    SafariPressKeyTool,
    # Chrome tools
    ChromeOpenTool,
    ChromeNavigateTool,
    ChromeGetContentTool,
    ChromeClickTool,
    ChromeTypeTool,
    ChromePressKeyTool,
    # Edge tools (Windows)
    EdgeOpenTool,
    EdgeNavigateTool,
    EdgeGetContentTool,
    EdgeSearchTool,
    EdgePressKeyTool,
)
from .scheduler_tools import ScheduleTaskTool, ListScheduledTasksTool, CancelScheduledTaskTool
from .dynamic import DynamicToolLoader
from .skills import SkillLoader, SkillToToolConverter

# Platform detection
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"


# Built-in tools that are always available
BUILTIN_TOOLS: list[type[BasePlannerTool]] = [
    # System tools
    ShellTool,
    ListProcessesTool,
    KillProcessTool,
    OpenAppTool,
    CloseAppTool,
    ListAppsTool,
    GetSystemInfoTool,
    AskUserTool,
    # File tools
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    SearchFilesTool,
    # Network tools
    FetchURLTool,
    # Scheduler tools
    ScheduleTaskTool,
    ListScheduledTasksTool,
    CancelScheduledTaskTool,
    # Browser tools (cross-platform via Playwright)
    BrowserNavigateTool,
    BrowserClickTool,
    BrowserTypeTool,
    BrowserScreenshotTool,
    BrowserGetContentTool,
    BrowserWaitTool,
    BrowserScrollTool,
    BrowserExecuteScriptTool,
    BrowserNewTabTool,
    BrowserCloseTabTool,
    BrowserGetUrlTool,
    BrowserReloadTool,
    BrowserPressKeyTool,
    BrowserSelectOptionTool,
    BrowserGetAttributeTool,
    # Chrome native tools (cross-platform)
    ChromeOpenTool,
    ChromeNavigateTool,
    ChromeGetContentTool,
    ChromeClickTool,
    ChromeTypeTool,
    ChromePressKeyTool,
]

# macOS-specific tools
MACOS_TOOLS: list[type[BasePlannerTool]] = [
    AppleScriptTool,
    SafariOpenTool,
    SafariNavigateTool,
    SafariGetContentTool,
    SafariClickTool,
    SafariTypeTool,
    SafariPressKeyTool,
]

# Windows-specific tools
WINDOWS_TOOLS: list[type[BasePlannerTool]] = [
    PowerShellTool,
    WindowsSendKeysTool,
    WindowsFocusWindowTool,
    WindowsScreenshotTool,
    EdgeOpenTool,
    EdgeNavigateTool,
    EdgeGetContentTool,
    EdgeSearchTool,
    EdgePressKeyTool,
]


class ToolRegistry:
    """Registry for all planner tools"""

    def __init__(self, plugin: Any):
        self.plugin = plugin
        self._builtin_tools: dict[str, BasePlannerTool] = {}
        self._dynamic_loader: DynamicToolLoader | None = None
        self._skill_loader: SkillLoader | None = None
        self._initialized = False

    async def initialize(self):
        """Initialize the tool registry"""
        if self._initialized:
            return

        import logging
        logger = logging.getLogger(__name__)

        # Determine which tools to load based on platform
        tools_to_load = list(BUILTIN_TOOLS)
        
        if IS_MACOS:
            tools_to_load.extend(MACOS_TOOLS)
            logger.info("Loading macOS-specific tools")
        elif IS_WINDOWS:
            tools_to_load.extend(WINDOWS_TOOLS)
            logger.info("Loading Windows-specific tools")

        # Register built-in tools
        logger.info(f"开始初始化工具注册表，工具数量: {len(tools_to_load)}")
        for tool_class in tools_to_load:
            try:
                tool = tool_class()
                self._builtin_tools[tool.name] = tool
                logger.debug(f"注册工具: {tool.name}")
            except Exception as e:
                logger.error(f"注册工具失败 {tool_class}: {e}")

        logger.info(f"注册了 {len(self._builtin_tools)} 个内置工具")

        # Initialize dynamic tool loader
        self._dynamic_loader = DynamicToolLoader(self.plugin)

        # Initialize skill loader
        config = self.plugin.get_config() if self.plugin else {}
        self._skill_loader = SkillLoader(config)
        await self._skill_loader.initialize()

        # Register skills as tools
        await self._register_skills()

        self._initialized = True
        logger.info(f"工具注册表初始化完成，共 {len(self._builtin_tools)} 个工具")

    async def _register_skills(self):
        """Register loaded skills as tools"""
        import logging
        logger = logging.getLogger(__name__)
        
        if not self._skill_loader:
            logger.debug("Skill loader not available")
            return

        skills = self._skill_loader.get_all_skills()
        logger.info(f"Found {len(skills)} skills to register")
        
        for skill in skills:
            tool = SkillToToolConverter.convert(skill)
            if tool:
                self._builtin_tools[tool.name] = tool
                logger.info(f"[SKILL] Registered skill as tool: {tool.name} (source: {skill.source})")
                print(f"[DEBUG] Registered skill as tool: {tool.name} (source: {skill.source})")
            else:
                logger.warning(f"[SKILL] Failed to convert skill to tool: {skill.name}")

    def get_tool(self, name: str) -> BasePlannerTool | None:
        """Get a tool by name"""
        return self._builtin_tools.get(name)

    def get_all_tools(self) -> list[BasePlannerTool]:
        """Get all registered tools"""
        return list(self._builtin_tools.values())

    def to_openai_format(self) -> list:
        """Convert all tools to LangBot LLMTool format for native tool calling
        
        Returns:
            List of LLMTool instances for use with invoke_llm
        """
        return [tool.to_llm_tool() for tool in self._builtin_tools.values()]

    async def load_dynamic_tools(self) -> list[BasePlannerTool]:
        """Load dynamic tools from MCP servers and plugins"""
        if not self._dynamic_loader:
            return []

        dynamic_tools = await self._dynamic_loader.load_all_tools()

        # Register dynamic tools (they override built-ins with same name)
        for tool in dynamic_tools:
            if tool.name not in self._builtin_tools:
                self._builtin_tools[tool.name] = tool

        return dynamic_tools

    def get_tools_description(self) -> str:
        """Generate a description of all available tools for the LLM"""
        lines = []
        for tool in self._builtin_tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
            params = tool.parameters.get("properties", {})
            for param_name, param_info in params.items():
                required = " (required)" if param_name in tool.parameters.get("required", []) else ""
                lines.append(f"  - {param_name}: {param_info.get('description', '')}{required}")

        return "\n".join(lines)

    def create_filtered_copy(self, exclude_names: set[str]) -> 'ToolRegistry':
        """Create a shallow copy of this registry with certain tools excluded.

        Useful for scheduled task execution where scheduler tools should be excluded
        to prevent recursive task creation.
        """
        copy = ToolRegistry.__new__(ToolRegistry)
        copy.plugin = self.plugin
        copy._builtin_tools = {
            name: tool for name, tool in self._builtin_tools.items()
            if name not in exclude_names
        }
        copy._dynamic_loader = None
        copy._skill_loader = None
        copy._initialized = True
        return copy
