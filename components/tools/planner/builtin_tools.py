# Built-in tool execution for planner
# Handles execution of built-in tools that don't go through the registry

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from main import LangTARS

logger = logging.getLogger(__name__)


class BuiltinToolExecutor:
    """
    Executor for built-in tools.
    These are tools that are directly implemented in the helper plugin
    and don't need to go through the tool registry.
    """
    
    # List of built-in tool names
    BUILTIN_TOOLS = {
        "shell",
        "read_file",
        "write_file",
        "list_directory",
        "list_processes",
        "kill_process",
        "open_app",
        "close_app",
        "list_apps",
        "get_system_info",
        "search_files",
        "ask_user",
        "fetch_url",
    }
    
    @classmethod
    def is_builtin_tool(cls, tool_name: str) -> bool:
        """Check if a tool is a built-in tool"""
        return tool_name in cls.BUILTIN_TOOLS
    
    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        helper_plugin: 'LangTARS',
    ) -> dict[str, Any]:
        """
        Execute a built-in tool.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments
            helper_plugin: Helper plugin instance with tool implementations
            
        Returns:
            Tool execution result
        """
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
            return await self._fetch_url(arguments.get('url', ''))
        
        else:
            return {"error": f"Unknown built-in tool: {tool_name}"}
    
    async def _fetch_url(self, url: str) -> dict[str, Any]:
        """
        Fetch content from a URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            Fetch result with content
        """
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


# Dangerous operation patterns for confirmation
DANGEROUS_PATTERNS = {
    "shell": [
        # Delete commands
        'rm -rf', 'rm -r', 'rm -f', 'rmdir', 'del /f', 'del /s', 'rd /s',
        # Disk operations
        'dd ', 'mkfs', 'format ', 'diskpart', 'fdisk',
        # System critical operations
        'reboot', 'shutdown', 'poweroff', 'halt', 'init 0', 'init 6',
        # Permission changes
        'chmod 777', 'chown', 'chgrp',
        # Dangerous redirects
        '> /dev/', '>/dev/',
        # Windows dangerous commands
        'bcdedit', 'reg delete', 'taskkill /f',
    ],
    "applescript": [
        'do shell script "rm', 'do shell script "sudo', 'shutdown', 'reboot'
    ],
}


def needs_confirmation(tool_name: str, arguments: dict[str, Any]) -> bool:
    """
    Check if a tool execution needs user confirmation.
    
    Args:
        tool_name: Name of the tool
        arguments: Tool arguments
        
    Returns:
        True if confirmation is needed
    """
    # Tools that always need confirmation
    if tool_name in ['kill_process', 'delete_file', 'rm']:
        return True
    
    # Shell commands with dangerous patterns
    if tool_name in ['shell', 'run_command'] and arguments.get('command', ''):
        cmd = arguments['command'].lower()
        for pattern in DANGEROUS_PATTERNS.get('shell', []):
            if pattern in cmd:
                return True
    
    # AppleScript with dangerous patterns
    if tool_name == 'applescript' and arguments.get('script', ''):
        script = arguments['script'].lower()
        for pattern in DANGEROUS_PATTERNS.get('applescript', []):
            if pattern in script:
                return True
    
    return False


def build_confirmation_message(tool_name: str, arguments: dict[str, Any]) -> str:
    """
    Build a confirmation message for dangerous operations.
    
    Args:
        tool_name: Name of the tool
        arguments: Tool arguments
        
    Returns:
        Formatted confirmation message
    """
    msg = f"⚠️ 危险操作确认\n\n"
    msg += f"工具: {tool_name}\n"
    
    if tool_name == 'shell':
        msg += f"命令: {arguments.get('command', '')}\n"
    elif tool_name == 'kill_process':
        msg += f"目标: {arguments.get('target', '')}\n"
    elif tool_name == 'delete_file':
        msg += f"文件: {arguments.get('path', '')}\n"
    
    msg += "\n请回复「!tars yes」确认执行，回复「!tars no」取消，回复「!tars other」执行新命令。"
    
    return msg


# Global executor instance
_executor = BuiltinToolExecutor()


def get_builtin_executor() -> BuiltinToolExecutor:
    """Get the global built-in tool executor"""
    return _executor
