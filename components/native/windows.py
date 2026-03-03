# Windows Control - Native Windows control via PowerShell / COM automation
# Provides equivalent functionality to AppleScript on macOS

from __future__ import annotations

import asyncio
import platform
from typing import Any


def is_windows() -> bool:
    """Check if the current platform is Windows."""
    return platform.system() == "Windows"


class WindowsController:
    """Controller for native Windows automation via PowerShell."""

    def __init__(self, run_shell_func):
        """Initialize with a function that executes shell commands.

        Args:
            run_shell_func: An async function (command, timeout, working_dir) -> dict
        """
        self._run_shell = run_shell_func

    # ========== PowerShell Execution ==========

    async def run_powershell(self, script: str, timeout: int = 30) -> dict[str, Any]:
        """Execute a PowerShell script.

        This is the Windows equivalent of AppleScript execution on macOS.
        """
        if not script:
            return {"success": False, "error": "No script provided"}

        # Encode script to base64 to avoid escaping issues
        import base64
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        cmd = f'powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}'

        result = await self._run_shell(cmd, timeout=timeout)
        if result.get("success"):
            return {
                "success": True,
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "returncode": result.get("returncode", 0),
            }
        return {
            "success": False,
            "error": result.get("stderr", result.get("error", "PowerShell execution failed")),
            "stdout": result.get("stdout", ""),
        }

    # ========== Application Control ==========

    async def open_app(self, app_name: str | None = None, url: str | None = None) -> dict[str, Any]:
        """Open an application or URL on Windows."""
        if url:
            cmd = f'Start-Process "{url}"'
            result = await self.run_powershell(cmd)
            return {
                "success": result.get("success", False),
                "message": f"Opened {url}" if result.get("success") else result.get("error", "Failed"),
            }

        if app_name:
            # Try common app name mappings
            app_map = {
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "explorer": "explorer.exe",
                "paint": "mspaint.exe",
                "terminal": "wt.exe",
                "cmd": "cmd.exe",
                "powershell": "powershell.exe",
                "edge": "msedge.exe",
                "chrome": "chrome.exe",
                "firefox": "firefox.exe",
            }
            exe = app_map.get(app_name.lower(), app_name)
            cmd = f'Start-Process "{exe}"'
            result = await self.run_powershell(cmd)
            return {
                "success": result.get("success", False),
                "message": f"Opened {app_name}" if result.get("success") else result.get("error", "Failed"),
            }

        return {"success": False, "error": "No target specified"}

    async def close_app(self, app_name: str, force: bool = False) -> dict[str, Any]:
        """Close an application on Windows."""
        if force:
            cmd = f'Stop-Process -Name "{app_name}" -Force -ErrorAction SilentlyContinue'
        else:
            # Graceful close: try to close main window first
            cmd = f'''
$procs = Get-Process -Name "{app_name}" -ErrorAction SilentlyContinue
if ($procs) {{
    foreach ($p in $procs) {{
        $p.CloseMainWindow() | Out-Null
    }}
    "Closed {app_name}"
}} else {{
    "No process found: {app_name}"
}}
'''
        result = await self.run_powershell(cmd)
        return {
            "success": result.get("success", False),
            "message": f"Closed {app_name}" if result.get("success") else result.get("error", "Failed"),
        }

    async def list_apps(self, limit: int = 20) -> dict[str, Any]:
        """List running applications with visible windows on Windows."""
        cmd = f'''
Get-Process | Where-Object {{$_.MainWindowTitle -ne ""}} |
    Select-Object -First {limit} -Property ProcessName, Id, MainWindowTitle |
    ForEach-Object {{ "$($_.ProcessName) (PID: $($_.Id)) - $($_.MainWindowTitle)" }}
'''
        result = await self.run_powershell(cmd)
        if result.get("success"):
            apps = [a.strip() for a in result.get("stdout", "").strip().split("\n") if a.strip()]
            return {"success": True, "apps": apps, "count": len(apps)}
        return {"success": False, "error": result.get("error", "Failed"), "apps": []}

    async def get_frontmost_app(self) -> dict[str, Any]:
        """Get the foreground (active) window application."""
        cmd = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinAPI {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$hwnd = [WinAPI]::GetForegroundWindow()
$pid = 0
[WinAPI]::GetWindowThreadProcessId($hwnd, [ref]$pid) | Out-Null
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
if ($proc) { "$($proc.ProcessName) - $($proc.MainWindowTitle)" }
else { "Unknown" }
'''
        result = await self.run_powershell(cmd)
        if result.get("success"):
            return {"success": True, "app_name": result.get("stdout", "").strip()}
        return {"success": False, "error": result.get("error", "Failed")}

    # ========== System Information ==========

    async def get_system_info(self) -> dict[str, Any]:
        """Get Windows system information."""
        cmd = '''
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$mem = $os
$uptime = (Get-Date) - $os.LastBootUpTime
$info = @{
    OS = "$($os.Caption) $($os.Version)"
    Computer = $env:COMPUTERNAME
    User = $env:USERNAME
    CPU = $cpu.Name
    TotalMemoryGB = [math]::Round($mem.TotalVisibleMemorySize / 1MB, 2)
    FreeMemoryGB = [math]::Round($mem.FreePhysicalMemory / 1MB, 2)
    Uptime = "$($uptime.Days)d $($uptime.Hours)h $($uptime.Minutes)m"
}
$info.GetEnumerator() | ForEach-Object { "$($_.Key): $($_.Value)" }
'''
        result = await self.run_powershell(cmd)
        if result.get("success"):
            return {"success": True, "info_text": result.get("stdout", "").strip()}
        return {"success": False, "error": result.get("error", "Failed")}

    # ========== Process Management ==========

    async def list_processes(self, filter_pattern: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List running processes on Windows."""
        if filter_pattern:
            cmd = f'''
Get-Process | Where-Object {{ $_.ProcessName -match "{filter_pattern}" }} |
    Sort-Object CPU -Descending |
    Select-Object -First {limit} -Property Id, ProcessName, CPU, @{{N="MemMB";E={{[math]::Round($_.WorkingSet64/1MB,1)}}}} |
    ForEach-Object {{ "$($_.Id)`t$($_.CPU)`t$($_.MemMB)MB`t$($_.ProcessName)" }}
'''
        else:
            cmd = f'''
Get-Process |
    Sort-Object CPU -Descending |
    Select-Object -First {limit} -Property Id, ProcessName, CPU, @{{N="MemMB";E={{[math]::Round($_.WorkingSet64/1MB,1)}}}} |
    ForEach-Object {{ "$($_.Id)`t$($_.CPU)`t$($_.MemMB)MB`t$($_.ProcessName)" }}
'''
        result = await self.run_powershell(cmd)
        if not result.get("success"):
            return {"success": False, "error": result.get("error"), "processes": []}

        processes = []
        for line in result.get("stdout", "").strip().split("\n"):
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                processes.append({
                    "pid": parts[0],
                    "cpu": parts[1],
                    "mem": parts[2],
                    "command": parts[3],
                })
        return {"success": True, "processes": processes[:limit]}

    async def kill_process(self, target: str, force: bool = False) -> dict[str, Any]:
        """Kill a process by name or PID on Windows."""
        if target.isdigit():
            cmd = f'Stop-Process -Id {target} {"- Force" if force else ""} -ErrorAction SilentlyContinue'
        else:
            cmd = f'Stop-Process -Name "{target}" {"-Force" if force else ""} -ErrorAction SilentlyContinue'
        result = await self.run_powershell(cmd)
        return {
            "success": result.get("success", False),
            "message": f"Killed {target}" if result.get("success") else result.get("error", "Failed"),
        }

    # ========== File Search (Windows-native) ==========

    async def search_files(self, pattern: str, path: str = ".", recursive: bool = True) -> dict[str, Any]:
        """Search for files matching a pattern on Windows."""
        recurse = "-Recurse" if recursive else ""
        cmd = f'''
Get-ChildItem -Path "{path}" {recurse} -Filter "*{pattern}*" -File -ErrorAction SilentlyContinue |
    Select-Object -First 50 -ExpandProperty FullName
'''
        result = await self.run_powershell(cmd)
        if result.get("success"):
            files = [f.strip() for f in result.get("stdout", "").strip().split("\n") if f.strip()]
            return {"success": True, "files": files, "count": len(files)}
        return {"success": False, "error": result.get("error"), "files": []}


class WindowsChromeController:
    """Controller for native Chrome browser on Windows via PowerShell/COM."""

    def __init__(self, run_shell_func):
        self._run_shell = run_shell_func
        self._windows = WindowsController(run_shell_func)

    async def open(self, url: str | None = None) -> dict[str, Any]:
        """Open Chrome on Windows."""
        if url:
            return await self.navigate(url)
        cmd = 'Start-Process "chrome.exe"'
        return await self._windows.run_powershell(cmd)

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to URL in Chrome on Windows."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        url_escaped = url.replace('"', '`"')
        cmd = f'Start-Process "chrome.exe" -ArgumentList "{url_escaped}"'
        return await self._windows.run_powershell(cmd)

    async def get_content(self) -> dict[str, Any]:
        """Get content - not natively supported without DevTools Protocol.
        Returns guidance to use Playwright browser instead.
        """
        return {
            "success": False,
            "error": "Native Chrome content reading is not supported on Windows. Use Playwright browser (default) for page content.",
        }

    async def click(self, selector: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for DOM interaction on Windows."}

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for DOM interaction on Windows."}

    async def press_key(self, key: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for keyboard interaction on Windows."}


class WindowsEdgeController:
    """Controller for native Edge browser on Windows.
    Edge is the Windows equivalent of Safari on macOS.
    """

    def __init__(self, run_shell_func):
        self._run_shell = run_shell_func
        self._windows = WindowsController(run_shell_func)

    async def open(self, url: str | None = None) -> dict[str, Any]:
        """Open Edge on Windows."""
        if url:
            return await self.navigate(url)
        cmd = 'Start-Process "msedge.exe"'
        return await self._windows.run_powershell(cmd)

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to URL in Edge on Windows."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        url_escaped = url.replace('"', '`"')
        cmd = f'Start-Process "msedge.exe" -ArgumentList "{url_escaped}"'
        return await self._windows.run_powershell(cmd)

    async def get_content(self) -> dict[str, Any]:
        return {
            "success": False,
            "error": "Native Edge content reading is not supported. Use Playwright browser (default) for page content.",
        }

    async def click(self, selector: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for DOM interaction on Windows."}

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for DOM interaction on Windows."}

    async def press_key(self, key: str) -> dict[str, Any]:
        return {"success": False, "error": "Use Playwright browser for keyboard interaction on Windows."}
