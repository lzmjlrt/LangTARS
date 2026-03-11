# LangTARS Plugin for LangBot
# Control your computer through IM messages (supports macOS, Windows and Linux)

from __future__ import annotations

import locale
import logging
import platform

from components.helpers.logging_setup import setup_langtars_file_logging

# Ensure root logger has stream + file handlers even if host already configured logging
setup_langtars_file_logging()
logger = logging.getLogger(__name__)

from langbot_plugin.api.definition.components.command.command import Command, Subcommand
from langbot_plugin.api.definition.plugin import BasePlugin
from langbot_plugin.api.entities.builtin.command.context import ExecuteContext, CommandReturn

from components.helpers.browser import BrowserController
from components.commands.langtars import LanTARSCommand

# Platform detection
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Detect system encoding for subprocess output (GBK/cp936 on Chinese Windows, etc.)
SYSTEM_ENCODING = locale.getpreferredencoding(False) or 'utf-8'
logger.warning(f"[LangTARS] System subprocess encoding: {SYSTEM_ENCODING}")

# Import platform-specific modules
if IS_MACOS:
    from components.native.safari import SafariController
    from components.native.chrome import ChromeController
elif IS_WINDOWS:
    from components.native.windows import WindowsController
    from components.native.edge import EdgeController
    from components.native.chrome_windows import ChromeWindowsController


class LangTARS(Command, BasePlugin):
    """LangTARS Plugin - Control your computer through IM messages"""

    DANGEROUS_PATTERNS = [
        r'rm\s+-rf\s+/', r'mkfs', r'dd\s+if=/dev/zero', r':(){:|:&};:',
        r'chmod\s+777\s+/', r'sudo\s+.*', r'>\s*/dev/', r'&\s*>/dev/',
        # Windows dangerous patterns
        r'format\s+[a-z]:', r'del\s+/[sfq]', r'rd\s+/s', r'rmdir\s+/s',
        r'reg\s+delete', r'bcdedit', r'diskpart',
    ]

    def __init__(self):
        super().__init__()
        self.config: dict = {}
        self._workspace_path = None
        self._allowed_users: set = set()
        self._command_whitelist: list = []
        self._initialized = False
        self._platform = platform.system()

        # Controllers
        self._browser: BrowserController | None = None
        
        # macOS controllers
        self._safari: "SafariController | None" = None
        self._chrome: "ChromeController | None" = None
        
        # Windows controllers
        self._windows: "WindowsController | None" = None
        self._edge: "EdgeController | None" = None
        self._chrome_win: "ChromeWindowsController | None" = None

        # Register subcommands - delegate to LanTARSCommand
        self.registered_subcommands = {
            "stop": Subcommand(subcommand=LanTARSCommand.stop, help="Stop task", usage="!tars stop", aliases=["pause", "停止"]),
            "what": Subcommand(subcommand=LanTARSCommand.what, help="What is the agent doing now", usage="!tars what", aliases=["状态", "进度"]),
            "yes": Subcommand(subcommand=LanTARSCommand.confirm, help="Confirm dangerous operation", usage="!tars yes", aliases=["y", "confirm", "ok", "同意", "好", "确认"]),
            "no": Subcommand(subcommand=LanTARSCommand.deny, help="Deny dangerous operation", usage="!tars no", aliases=["n", "cancel", "deny", "不同意", "不", "取消"]),
            "other": Subcommand(subcommand=LanTARSCommand.other, help="Provide new instruction", usage="!tars other <new instruction>", aliases=["新任务", "改变任务"]),
            "help": Subcommand(subcommand=LanTARSCommand.help, help="Show command help", usage="!tars help", aliases=["h", "?", "帮助"]),
            "reset": Subcommand(subcommand=LanTARSCommand.reset, help="Reset conversation history", usage="!tars reset", aliases=["清空", "重置", "clear"]),
            "config": Subcommand(subcommand=self.cmd_config, help="Config", usage="!tars config [save]", aliases=["cfg"]),
            "*": Subcommand(subcommand=LanTARSCommand.default, help="Help", usage="!tars help", aliases=[]),
        }

    # ========== Config ==========

    def get_config(self) -> dict:
        return self.config

    def _get_config_file_path(self):
        from pathlib import Path
        config_dir = Path.home() / ".langtars"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def _load_config_from_file(self) -> dict:
        import json
        config_file = self._get_config_file_path()
        if config_file.exists():
            try:
                return json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_config_to_file(self, config: dict) -> None:
        import json
        config_file = self._get_config_file_path()
        try:
            config_file.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Failed to save config: {e}")

    def set_config(self, config: dict) -> None:
        self.config = config
        self._save_config_to_file(config)

    async def initialize(self) -> None:
        local_config = self._load_config_from_file()

        for key in ['planner_max_iterations', 'planner_rate_limit_seconds', 'browser_timeout']:
            if key in local_config and isinstance(local_config[key], str):
                try:
                    local_config[key] = int(local_config[key])
                except (ValueError, TypeError):
                    pass

        self.config = self.config or {}
        if local_config:
            self.config = {**local_config, **self.config}

        if 'planner_rate_limit_seconds' not in self.config:
            self.config['planner_rate_limit_seconds'] = 3
        elif isinstance(self.config['planner_rate_limit_seconds'], str):
            try:
                self.config['planner_rate_limit_seconds'] = int(self.config['planner_rate_limit_seconds'])
            except (ValueError, TypeError):
                self.config['planner_rate_limit_seconds'] = 3

        from pathlib import Path
        workspace = self.config.get('workspace_path', '~/.langtars')
        self._workspace_path = Path(workspace).expanduser()
        self._workspace_path.mkdir(parents=True, exist_ok=True)
        self._allowed_users = set(self.config.get('allowed_users', []))
        self._command_whitelist = self.config.get('command_whitelist', [])
        self._initialized = True
        self._save_config_to_file(self.config)

        # Initialize controllers based on platform
        self._browser = BrowserController(self.config)
        
        if IS_MACOS:
            self._safari = SafariController(self.run_applescript)
            self._chrome = ChromeController(self.run_applescript)
        elif IS_WINDOWS:
            self._windows = WindowsController(self.run_powershell)
            self._edge = EdgeController(self.run_powershell)
            self._chrome_win = ChromeWindowsController(self.run_powershell)

    # ========== Safety ==========

    def is_user_allowed(self, user_id: str) -> bool:
        return not self._allowed_users or user_id in self._allowed_users

    def is_command_allowed(self, command: str) -> bool:
        if not self._command_whitelist:
            return True
        cmd_base = command.strip().split()[0] if command.strip() else ''
        return cmd_base in self._command_whitelist

    def check_dangerous_pattern(self, command: str) -> tuple[bool, str]:
        import re
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True, f"Dangerous pattern: {pattern}"
        return False, ""

    # ========== Shell Execution ==========

    async def run_shell(self, command: str, timeout: int = 30, working_dir: str | None = None) -> dict:
        import asyncio
        from pathlib import Path

        if not self.config.get('enable_shell', True):
            return {'success': False, 'error': 'Shell disabled', 'stdout': '', 'stderr': '', 'returncode': -1}
        if not self.is_command_allowed(command):
            return {'success': False, 'error': 'Command not in whitelist', 'stdout': '', 'stderr': '', 'returncode': -1}
        is_dangerous, danger_msg = self.check_dangerous_pattern(command)
        if is_dangerous:
            return {'success': False, 'error': f'Blocked: {danger_msg}', 'stdout': '', 'stderr': '', 'returncode': -1}

        working_path = self._workspace_path
        if working_dir:
            wp = Path(working_dir).expanduser().resolve()
            # Check if sandbox mode is disabled - allow any working directory
            if not self.config.get('sandbox_mode', True):
                working_path = wp
            elif str(wp).startswith(str(self._workspace_path.resolve())):
                working_path = wp

        try:
            # Use different shell based on platform
            if IS_WINDOWS:
                process = await asyncio.create_subprocess_shell(
                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(working_path), shell=True)
            else:
                process = await asyncio.create_subprocess_shell(
                    command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(working_path))
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return {'success': False, 'error': f'Timeout after {timeout}s', 'stdout': '', 'stderr': '', 'returncode': -1}
            # Decode with system encoding on Windows (e.g. cp936 for Chinese), UTF-8 on Unix
            encoding = SYSTEM_ENCODING if IS_WINDOWS else 'utf-8'
            return {
                'success': process.returncode == 0,
                'stdout': stdout.decode(encoding, errors='replace'),
                'stderr': stderr.decode(encoding, errors='replace'),
                'returncode': process.returncode, 'error': '',
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'stdout': '', 'stderr': '', 'returncode': -1}

    async def run_powershell(self, script: str, timeout: int = 30) -> dict:
        """Execute a PowerShell script (Windows only)."""
        import asyncio
        import tempfile
        import os

        if not IS_WINDOWS:
            return {'success': False, 'error': 'PowerShell is only available on Windows'}

        if not self.config.get('enable_powershell', True):
            return {'success': False, 'error': 'PowerShell disabled'}

        if not script:
            return {'success': False, 'error': 'No script provided'}

        try:
            # Write script to temp file to handle complex scripts
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
                f.write(script)
                temp_file = f.name

            try:
                # Execute PowerShell with the script file, forcing UTF-8 output
                cmd = (
                    f'powershell.exe -ExecutionPolicy Bypass -NoProfile -Command '
                    f'"[Console]::OutputEncoding = [Text.Encoding]::UTF8; '
                    f'& \'{temp_file}\'"'
                )
                process = await asyncio.create_subprocess_shell(
                    cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                except asyncio.TimeoutError:
                    process.kill()
                    return {'success': False, 'error': f'Timeout after {timeout}s', 'stdout': '', 'stderr': ''}
                
                return {
                    'success': process.returncode == 0,
                    'stdout': stdout.decode('utf-8', errors='replace'),
                    'stderr': stderr.decode('utf-8', errors='replace'),
                    'returncode': process.returncode,
                    'error': stderr.decode('utf-8', errors='replace') if process.returncode != 0 else '',
                }
            finally:
                try:
                    os.unlink(temp_file)
                except:
                    pass
        except Exception as e:
            return {'success': False, 'error': str(e), 'stdout': '', 'stderr': ''}

    def _resolve_path(self, path: str):
        from pathlib import Path
        import os
        if not self._workspace_path:
            return None
        try:
            requested = Path(path).expanduser()
            
            # Check if sandbox mode is disabled - allow global file access
            if not self.config.get('sandbox_mode', True):
                if requested.is_absolute():
                    return requested.resolve()
                # For relative paths, still use workspace as base
                return (self._workspace_path / requested).resolve()
            
            # Sandbox mode enabled - restrict to workspace directory
            workspace_resolved = self._workspace_path.resolve()
            
            if requested.is_absolute():
                resolved = requested.resolve()
                # Use os.path.commonpath for more robust path comparison on Windows
                # This handles case-insensitivity and different path separators
                try:
                    common = Path(os.path.commonpath([str(resolved), str(workspace_resolved)]))
                    # Compare resolved paths to handle case-insensitivity on Windows
                    if common.resolve() != workspace_resolved:
                        return None
                except ValueError:
                    # commonpath raises ValueError if paths are on different drives
                    return None
                return resolved
            return (self._workspace_path / requested).resolve()
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"_resolve_path error for '{path}': {e}")
            return None

    # ========== Helper Methods ==========

    async def list_processes(self, filter_pattern: str | None = None, limit: int = 20) -> dict:
        if not self.config.get('enable_process', True):
            return {'success': False, 'error': 'Disabled', 'processes': []}
        
        if IS_WINDOWS:
            # Use Windows controller
            if self._windows:
                return await self._windows.list_processes(filter_pattern, limit)
            return {'success': False, 'error': 'Windows controller not initialized', 'processes': []}
        else:
            # macOS/Linux
            cmd = f'ps aux | grep -E "{filter_pattern}" | grep -v grep | head -n {limit}' if filter_pattern else f'ps aux | head -n {limit + 1}'
            result = await self.run_shell(cmd)
            if not result['success']:
                return {'success': False, 'error': result.get('error'), 'processes': []}
            processes = []
            for line in result['stdout'].strip().split('\n'):
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({'user': parts[0], 'pid': parts[1], 'cpu': parts[2], 'mem': parts[3], 'command': parts[10]})
            return {'success': True, 'processes': processes[:limit]}

    async def kill_process(self, target: str, force: bool = False) -> dict:
        if not self.config.get('enable_process', True):
            return {'success': False, 'error': 'Disabled'}
        
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.kill_process(target, force)
            return {'success': False, 'error': 'Windows controller not initialized'}
        else:
            cmd = f'kill -{"KILL" if force else "TERM"} {target}' if target.isdigit() else f'pkill -{"KILL" if force else "TERM"} "{target}"'
            result = await self.run_shell(cmd)
            return {'success': result['success'], 'message': f'Killed {target}' if result['success'] else result.get('error')}

    async def list_directory(self, path: str = ".", show_hidden: bool = False) -> dict:
        if not self.config.get('enable_file', True):
            return {'success': False, 'error': 'Disabled', 'items': []}
        dir_path = self._resolve_path(path)
        if not dir_path:
            return {'success': False, 'error': 'Access denied', 'items': []}
        try:
            items = [{'name': i.name, 'type': 'directory' if i.is_dir() else 'file', 'size': i.stat().st_size if i.is_file() else 0}
                     for i in dir_path.iterdir() if not i.name.startswith('.') or show_hidden]
            return {'success': True, 'path': str(dir_path), 'items': items, 'count': len(items)}
        except Exception as e:
            return {'success': False, 'error': str(e), 'items': []}

    async def read_file(self, path: str) -> dict:
        if not self.config.get('enable_file', True):
            return {'success': False, 'error': 'Disabled'}
        fp = self._resolve_path(path)
        if not fp:
            return {'success': False, 'error': f'Access denied: path "{path}" is outside workspace'}
        try:
            if not fp.exists():
                return {'success': False, 'error': f'File not found: {fp}'}
            if not fp.is_file():
                return {'success': False, 'error': f'Not a file (is directory): {fp}'}
            content = fp.read_text(encoding='utf-8')
            return {'success': True, 'path': str(fp), 'content': content, 'size': len(content)}
        except UnicodeDecodeError:
            return {'success': True, 'path': str(fp), 'is_binary': True, 'size': fp.stat().st_size}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def write_file(self, path: str, content: str, mode: str = "w") -> dict:
        if not self.config.get('enable_file', True):
            return {'success': False, 'error': 'Disabled'}
        fp = self._resolve_path(path)
        if not fp:
            return {'success': False, 'error': 'Access denied'}
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding='utf-8')
            return {'success': True, 'path': str(fp)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    async def open_app(self, app_name: str | None = None, url: str | None = None) -> dict:
        if not self.config.get('enable_app', True):
            return {'success': False, 'error': 'Disabled'}
        
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.open_app(app_name, url)
            return {'success': False, 'error': 'Windows controller not initialized'}
        elif IS_LINUX:
            # Linux: use xdg-open for URLs and applications
            if url:
                cmd = f'xdg-open "{url}"'
            elif app_name:
                # Try to launch application directly
                cmd = f'{app_name} &'
            else:
                return {'success': False, 'error': 'No target'}
            result = await self.run_shell(cmd)
            return {'success': result['success'], 'message': f'Opened {url or app_name}' if result['success'] else result.get('error')}
        else:
            # macOS
            cmd = f'open "{url}"' if url else f'open -a "{app_name}"' if app_name else None
            if not cmd:
                return {'success': False, 'error': 'No target'}
            result = await self.run_shell(cmd)
            return {'success': result['success'], 'message': f'Opened {url or app_name}' if result['success'] else result.get('error')}

    async def close_app(self, app_name: str, force: bool = False) -> dict:
        if not self.config.get('enable_app', True):
            return {'success': False, 'error': 'Disabled'}
        
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.close_app(app_name, force)
            return {'success': False, 'error': 'Windows controller not initialized'}
        else:
            # Linux and macOS both support pkill
            result = await self.run_shell(f'pkill -{"9" if force else "TERM"} "{app_name}"')
            return {'success': result['success'], 'message': f'Closed {app_name}' if result['success'] else result.get('error')}

    async def list_apps(self, limit: int = 20) -> dict:
        if not self.config.get('enable_app', True):
            return {'success': False, 'error': 'Disabled', 'apps': []}
        
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.list_apps(limit)
            return {'success': False, 'error': 'Windows controller not initialized', 'apps': []}
        elif IS_LINUX:
            # Linux: use ps to list processes with visible windows or common desktop apps
            result = await self.run_shell(f"ps -eo comm --no-headers | sort -u | head -n {limit}")
            if result['success']:
                apps = [a.strip() for a in result['stdout'].strip().split('\n') if a.strip()]
                return {'success': True, 'apps': apps, 'count': len(apps)}
            return {'success': False, 'error': result.get('error'), 'apps': []}
        else:
            # macOS
            result = await self.run_shell(f"osascript -e 'tell app \"System Events\" to get name of every process' | tr ',' '\\n' | head -n {limit}")
            if result['success']:
                apps = [a.strip() for a in result['stdout'].strip().split('\n') if a.strip()]
                return {'success': True, 'apps': apps, 'count': len(apps)}
            return {'success': False, 'error': result.get('error'), 'apps': []}

    async def get_system_info(self) -> dict:
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.get_system_info()
            return {'success': False, 'error': 'Windows controller not initialized'}
        else:
            try:
                info = {'platform': platform.system(), 'platform_version': platform.version(), 'architecture': platform.architecture()[0],
                       'processor': platform.processor(), 'hostname': platform.node(), 'python_version': platform.python_version()}
                ur = await self.run_shell('uptime')
                if ur['success']:
                    info['uptime'] = ur['stdout'].strip()
                return {'success': True, 'info': info}
            except Exception as e:
                return {'success': False, 'error': str(e)}

    async def search_files(self, pattern: str, path: str = ".", recursive: bool = True) -> dict:
        if not self.config.get('enable_file', True):
            return {'success': False, 'error': 'Disabled', 'files': []}
        sp = self._resolve_path(path)
        if not sp:
            return {'success': False, 'error': 'Access denied', 'files': []}
        
        if IS_WINDOWS:
            if self._windows:
                return await self._windows.search_files(pattern, str(sp), recursive)
            return {'success': False, 'error': 'Windows controller not initialized', 'files': []}
        else:
            cmd = f'find "{sp}" -name "*{pattern}*" -type f 2>/dev/null | head -n 50' if recursive else f'ls "{sp}" | grep -i "*{pattern}*" | head -n 50'
            result = await self.run_shell(cmd)
            if result['success']:
                files = [f.strip() for f in result['stdout'].strip().split('\n') if f.strip()]
                return {'success': True, 'files': files, 'count': len(files)}
            return {'success': False, 'error': result.get('error'), 'files': []}

    async def run_applescript(self, script: str) -> dict:
        """Execute AppleScript (macOS only)."""
        import tempfile, os
        
        if IS_WINDOWS:
            return {'success': False, 'error': 'AppleScript is only available on macOS. Use PowerShell on Windows.'}
        
        if not self.config.get('enable_applescript', True):
            return {'success': False, 'error': 'Disabled'}
        if not script:
            return {'success': False, 'error': 'No script'}
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False) as f:
                f.write(script)
                temp_file = f.name
            try:
                result = await self.run_shell(f'osascript "{temp_file}"')
            finally:
                try: os.unlink(temp_file)
                except: pass
            if result['success']:
                return {'success': True, 'stdout': result['stdout'], 'stderr': result['stderr'], 'returncode': result['returncode']}
            return {'success': False, 'error': result.get('stderr', result.get('error')), 'stdout': result.get('stdout')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ========== Windows-specific Methods ==========

    async def windows_send_keys(self, keys: str) -> dict:
        """Send keystrokes to the active window (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.send_keys(keys)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_type_text(self, text: str) -> dict:
        """Type text into the active window (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.type_text(text)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_press_key(self, key: str) -> dict:
        """Press a special key (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.press_key(key)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_get_active_window(self) -> dict:
        """Get information about the active window (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.get_active_window()
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_focus_window(self, title_or_process: str) -> dict:
        """Focus a window by title or process name (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.focus_window(title_or_process)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_minimize_window(self, title_or_process: str | None = None) -> dict:
        """Minimize a window (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.minimize_window(title_or_process)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_maximize_window(self, title_or_process: str | None = None) -> dict:
        """Maximize a window (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.maximize_window(title_or_process)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_screenshot(self, path: str | None = None) -> dict:
        """Take a screenshot (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.take_screenshot(path)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_get_clipboard(self) -> dict:
        """Get clipboard content (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.get_clipboard()
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_set_clipboard(self, text: str) -> dict:
        """Set clipboard content (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.set_clipboard(text)
        return {'success': False, 'error': 'Windows controller not initialized'}

    async def windows_show_notification(self, title: str, message: str) -> dict:
        """Show a Windows toast notification (Windows only)."""
        if not IS_WINDOWS:
            return {'success': False, 'error': 'This method is only available on Windows'}
        if self._windows:
            return await self._windows.show_notification(title, message)
        return {'success': False, 'error': 'Windows controller not initialized'}

    # ========== Browser/Safari/Chrome Delegates ==========

    async def browser_navigate(self, url: str): return await self._browser.navigate(url) if self._browser else {'success': False}
    async def browser_click(self, s): return await self._browser.click(s) if self._browser else {'success': False}
    async def browser_type(self, s, t, c=True): return await self._browser.type_text(s, t, c) if self._browser else {'success': False}
    async def browser_screenshot(self, p=None): return await self._browser.screenshot(p) if self._browser else {'success': False}
    async def browser_get_content(self, s=None): return await self._browser.get_content(s) if self._browser else {'success': False}
    async def browser_wait(self, s, t=30): return await self._browser.wait_for_selector(s, t) if self._browser else {'success': False}
    async def browser_scroll(self, x=0, y=500): return await self._browser.scroll(x, y) if self._browser else {'success': False}
    async def browser_execute_script(self, s): return await self._browser.execute_script(s) if self._browser else {'success': False}
    async def browser_new_tab(self, u="about:blank"): return await self._browser.new_tab(u) if self._browser else {'success': False}
    async def browser_close_tab(self): return await self._browser.close_tab() if self._browser else {'success': False}
    async def browser_get_url(self): return await self._browser.get_current_url() if self._browser else {'success': False}
    async def browser_reload(self): return await self._browser.reload() if self._browser else {'success': False}
    async def browser_press_key(self, s, k): return await self._browser.press_key(s, k) if self._browser else {'success': False}
    async def browser_select_option(self, s, v): return await self._browser.select_option(s, v) if self._browser else {'success': False}
    async def browser_get_attribute(self, s, a): return await self._browser.get_attribute(s, a) if self._browser else {'success': False}
    async def browser_cleanup(self): return await self._browser.cleanup() if self._browser else {'success': True}

    # macOS Safari delegates
    async def safari_open(self, u=None): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.open(u) if self._safari else {'success': False}
    async def safari_navigate(self, u): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.navigate(u) if self._safari else {'success': False}
    async def safari_get_content(self): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.get_content() if self._safari else {'success': False}
    async def safari_click(self, s): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.click(s) if self._safari else {'success': False}
    async def safari_type(self, s, t): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.type(s, t) if self._safari else {'success': False}
    async def safari_press_key(self, k): 
        if not IS_MACOS:
            return {'success': False, 'error': 'Safari is only available on macOS'}
        return await self._safari.press_key(k) if self._safari else {'success': False}

    # Chrome delegates (cross-platform)
    async def chrome_open(self, u=None): 
        if IS_MACOS:
            return await self._chrome.open(u) if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.open(u) if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}
    
    async def chrome_navigate(self, u): 
        if IS_MACOS:
            return await self._chrome.navigate(u) if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.navigate(u) if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}
    
    async def chrome_get_content(self): 
        if IS_MACOS:
            return await self._chrome.get_content() if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.get_content() if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}
    
    async def chrome_click(self, s): 
        if IS_MACOS:
            return await self._chrome.click(s) if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.click(s) if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}
    
    async def chrome_type(self, s, t): 
        if IS_MACOS:
            return await self._chrome.type(s, t) if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.type(s, t) if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}
    
    async def chrome_press_key(self, k): 
        if IS_MACOS:
            return await self._chrome.press_key(k) if self._chrome else {'success': False}
        elif IS_WINDOWS:
            return await self._chrome_win.press_key(k) if self._chrome_win else {'success': False}
        return {'success': False, 'error': 'Unsupported platform'}

    # Windows Edge delegates
    async def edge_open(self, u=None):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.open(u) if self._edge else {'success': False}
    
    async def edge_navigate(self, u):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.navigate(u) if self._edge else {'success': False}
    
    async def edge_get_content(self):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.get_content() if self._edge else {'success': False}
    
    async def edge_search(self, query: str):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.search(query) if self._edge else {'success': False}
    
    async def edge_press_key(self, k):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.press_key(k) if self._edge else {'success': False}
    
    async def edge_focus_and_type(self, text: str):
        if not IS_WINDOWS:
            return {'success': False, 'error': 'Edge native control is only available on Windows'}
        return await self._edge.focus_and_type(text) if self._edge else {'success': False}

    # ========== Permission Check ==========

    async def check_permissions(self) -> dict:
        """Check if required permissions are granted."""
        if IS_MACOS:
            result = await self.run_shell('osascript -e "tell application \\"System Events\\" to return name of first process"')
            if result['success']:
                return {'success': True, 'message': 'Accessibility permissions granted'}
            return {'success': False, 'error': 'Accessibility permissions not granted', 'instructions': self.get_permission_instructions()}
        elif IS_WINDOWS:
            return {'success': True, 'message': 'No special permissions required on Windows'}
        return {'success': False, 'error': 'Unsupported platform'}

    def get_permission_instructions(self) -> str:
        """Get instructions for granting permissions."""
        if IS_MACOS:
            return """To grant accessibility permissions on macOS:
1. Open System Preferences > Security & Privacy > Privacy
2. Select "Accessibility" from the left sidebar
3. Click the lock icon to make changes
4. Add your terminal application (Terminal, iTerm, etc.)
5. Restart the application"""
        elif IS_WINDOWS:
            return """Most operations on Windows don't require special permissions.
For some operations, you may need to:
1. Run as Administrator for system-level changes
2. Allow PowerShell script execution: Set-ExecutionPolicy RemoteSigned"""
        return "Unsupported platform"

    # ========== Commands ==========

    async def cmd_config(self, ctx: ExecuteContext) -> "CommandReturn":
        from langbot_plugin.api.entities.builtin.command.context import CommandReturn
        action = ctx.crt_params[0] if ctx.crt_params else "show"
        if action == "save":
            self._save_config_to_file(self.config)
            return CommandReturn(text=f"Saved to {self._get_config_file_path()}")
        keys = ['enable_shell', 'enable_process', 'enable_file', 'enable_app', 'planner_max_iterations', 'workspace_path']
        if IS_WINDOWS:
            keys.append('enable_powershell')
        else:
            keys.append('enable_applescript')
        return CommandReturn(text=f"Platform: {self._platform}\n" + "\n".join(f"{k}: {self.config.get(k)}" for k in keys))
