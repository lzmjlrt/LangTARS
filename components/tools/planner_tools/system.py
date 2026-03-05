# System tools for planner
# Shell, file, process, app management tools

from __future__ import annotations

import platform
from typing import Any

from . import BasePlannerTool

# Platform detection
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
PLATFORM_NAME = "Windows" if IS_WINDOWS else "Mac" if IS_MACOS else "Linux"


class ShellTool(BasePlannerTool):
    """Execute shell commands"""

    @property
    def name(self) -> str:
        return "shell"

    @property
    def description(self) -> str:
        if IS_WINDOWS:
            return "Execute a shell command on this Windows PC. Use this for running commands like dir, tasklist, findstr, curl, etc."
        return "Execute a shell command on this Mac. Use this for running terminal commands like ls, ps, grep, curl, etc."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 30)",
                    "default": 30
                }
            },
            "required": ["command"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.run_shell(
            command=arguments.get('command', ''),
            timeout=arguments.get('timeout', 30)
        )


class ListProcessesTool(BasePlannerTool):
    """List running processes"""

    @property
    def name(self) -> str:
        return "list_processes"

    @property
    def description(self) -> str:
        return f"List running processes on this {PLATFORM_NAME}."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Filter processes by name (optional)"
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum number of processes to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.list_processes(
            filter_pattern=arguments.get('filter'),
            limit=arguments.get('limit', 20)
        )


class KillProcessTool(BasePlannerTool):
    """Kill a process"""

    @property
    def name(self) -> str:
        return "kill_process"

    @property
    def description(self) -> str:
        return "Kill a process by name or PID."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Process name or PID to kill"
                },
                "force": {
                    "type": "boolean",
                    "description": "Force kill (default: false)",
                    "default": False
                }
            },
            "required": ["target"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.kill_process(
            target=arguments.get('target', ''),
            force=arguments.get('force', False)
        )


class OpenAppTool(BasePlannerTool):
    """Open an application or URL"""

    @property
    def name(self) -> str:
        return "open_app"

    @property
    def description(self) -> str:
        if IS_WINDOWS:
            return "Open an application or URL on this Windows PC. Examples: 'notepad', 'chrome', 'https://google.com'"
        return "Open an application or URL on this Mac. Examples: 'Safari', 'Chrome', 'https://google.com'"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Application name (e.g., 'Safari', 'notepad') or URL (e.g., 'https://...')"
                }
            },
            "required": ["target"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        target = arguments.get('target', '')
        is_url = target.startswith(('http://', 'https://', 'mailto:', 'tel:'))
        return await helper_plugin.open_app(
            app_name=None if is_url else target,
            url=target if is_url else None
        )


class CloseAppTool(BasePlannerTool):
    """Close an application"""

    @property
    def name(self) -> str:
        return "close_app"

    @property
    def description(self) -> str:
        return "Close an application by name."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The name of the application to close"
                },
                "force": {
                    "type": "boolean",
                    "description": "Force quit (default: false)",
                    "default": False
                }
            },
            "required": ["app_name"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.close_app(
            app_name=arguments.get('app_name', ''),
            force=arguments.get('force', False)
        )


class ListAppsTool(BasePlannerTool):
    """List running applications"""

    @property
    def name(self) -> str:
        return "list_apps"

    @property
    def description(self) -> str:
        return f"List running applications on this {PLATFORM_NAME}."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Maximum number of apps to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.list_apps(limit=arguments.get('limit', 20))


class GetSystemInfoTool(BasePlannerTool):
    """Get system information"""

    @property
    def name(self) -> str:
        return "get_system_info"

    @property
    def description(self) -> str:
        return f"Get system information about this {PLATFORM_NAME}."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        return await helper_plugin.get_system_info()


class AppleScriptTool(BasePlannerTool):
    """Execute AppleScript to control macOS applications (macOS only)"""

    @property
    def name(self) -> str:
        return "applescript"

    @property
    def description(self) -> str:
        if IS_WINDOWS:
            return "AppleScript is only available on macOS. Use 'powershell' tool instead on Windows."
        return """Execute AppleScript to control macOS applications. Use this to:
- Control applications (open, close, activate)
- Interact with UI elements (click, type, select)
- Automate browser operations in Chrome/Safari
- Control system settings
- Manipulate files and folders

Example for Chrome search:
tell application "Google Chrome"
    activate
    tell window 1
        set searchURL to "https://www.google.com/search?q=your+search+terms"
        set URL of active tab to searchURL
    end tell
end tell

Example for clicking UI element:
tell application "System Events"
    keystroke "hello"
end tell"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The AppleScript script to execute"
                }
            },
            "required": ["script"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if IS_WINDOWS:
            return {"success": False, "error": "AppleScript is only available on macOS. Use PowerShell on Windows."}
        
        script = arguments.get('script', '')
        if not script:
            return {"success": False, "error": "No script provided"}

        # Basic safety check - block potentially dangerous commands
        dangerous_patterns = ['rm -rf', 'format:', 'diskutil erase', 'do shell script "rm']
        for pattern in dangerous_patterns:
            if pattern.lower() in script.lower():
                return {"success": False, "error": f"Potentially dangerous command blocked: {pattern}"}

        return await helper_plugin.run_applescript(script)


class PowerShellTool(BasePlannerTool):
    """Execute PowerShell to control Windows applications (Windows only)"""

    @property
    def name(self) -> str:
        return "powershell"

    @property
    def description(self) -> str:
        if IS_MACOS:
            return "PowerShell is only available on Windows. Use 'applescript' tool instead on macOS."
        return """Execute PowerShell script to control Windows applications and system. Use this to:
- Control applications (open, close, focus windows)
- Interact with UI elements (send keys, type text)
- Automate browser operations in Edge/Chrome
- Control system settings
- Manage files and processes
- Access Windows APIs

Example for opening a URL in Edge:
Start-Process "msedge" -ArgumentList "https://www.google.com"

Example for sending keystrokes:
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("Hello World")

Example for getting system info:
Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script": {
                    "type": "string",
                    "description": "The PowerShell script to execute"
                }
            },
            "required": ["script"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if IS_MACOS:
            return {"success": False, "error": "PowerShell is only available on Windows. Use AppleScript on macOS."}
        
        script = arguments.get('script', '')
        if not script:
            return {"success": False, "error": "No script provided"}

        # Basic safety check - block potentially dangerous commands
        dangerous_patterns = ['format ', 'Remove-Item -Recurse -Force C:', 'rd /s', 'del /f /s', 'diskpart', 'bcdedit']
        for pattern in dangerous_patterns:
            if pattern.lower() in script.lower():
                return {"success": False, "error": f"Potentially dangerous command blocked: {pattern}"}

        return await helper_plugin.run_powershell(script)


class WindowsSendKeysTool(BasePlannerTool):
    """Send keystrokes to the active window (Windows only)"""

    @property
    def name(self) -> str:
        return "windows_send_keys"

    @property
    def description(self) -> str:
        if IS_MACOS:
            return "This tool is only available on Windows."
        return """Send keystrokes to the active window on Windows. Use this to:
- Type text into any application
- Press special keys (Enter, Tab, Escape, etc.)
- Use keyboard shortcuts (Ctrl+C, Alt+Tab, etc.)

Special key syntax:
- Enter: ~
- Tab: {TAB}
- Escape: {ESC}
- Ctrl+key: ^key (e.g., ^c for Ctrl+C)
- Alt+key: %key (e.g., %{F4} for Alt+F4)
- Shift+key: +key"""

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "string",
                    "description": "The keys to send (using SendKeys syntax)"
                }
            },
            "required": ["keys"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if IS_MACOS:
            return {"success": False, "error": "This tool is only available on Windows."}
        
        keys = arguments.get('keys', '')
        if not keys:
            return {"success": False, "error": "No keys provided"}

        return await helper_plugin.windows_send_keys(keys)


class WindowsFocusWindowTool(BasePlannerTool):
    """Focus a window by title or process name (Windows only)"""

    @property
    def name(self) -> str:
        return "windows_focus_window"

    @property
    def description(self) -> str:
        if IS_MACOS:
            return "This tool is only available on Windows."
        return "Bring a window to the foreground by its title or process name on Windows."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Window title or process name to focus"
                }
            },
            "required": ["target"]
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if IS_MACOS:
            return {"success": False, "error": "This tool is only available on Windows."}
        
        target = arguments.get('target', '')
        if not target:
            return {"success": False, "error": "No target provided"}

        return await helper_plugin.windows_focus_window(target)


class WindowsScreenshotTool(BasePlannerTool):
    """Take a screenshot (Windows only)"""

    @property
    def name(self) -> str:
        return "windows_screenshot"

    @property
    def description(self) -> str:
        if IS_MACOS:
            return "This tool is only available on Windows."
        return "Take a screenshot of the entire screen on Windows."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to save the screenshot (optional, defaults to temp folder)"
                }
            }
        }

    async def execute(self, helper_plugin: Any, arguments: dict[str, Any]) -> dict[str, Any]:
        if IS_MACOS:
            return {"success": False, "error": "This tool is only available on Windows."}
        
        return await helper_plugin.windows_screenshot(arguments.get('path'))
