# Windows Control - Native Windows control via PowerShell and COM

from __future__ import annotations

import asyncio
import platform
from typing import Any


def is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system() == "Windows"


class WindowsController:
    """Controller for native Windows system control using PowerShell."""

    def __init__(self, run_powershell_func):
        """Initialize with a function that executes PowerShell commands."""
        self._run_powershell = run_powershell_func

    async def open_app(self, app_name: str | None = None, url: str | None = None) -> dict[str, Any]:
        """Open an application or URL on Windows."""
        if url:
            # Open URL with default browser
            script = f'Start-Process "{url}"'
        elif app_name:
            # Try to open application by name
            # First try as a direct executable, then as a Start Menu item
            script = f'''
$app = "{app_name}"
# Try direct execution
try {{
    Start-Process $app -ErrorAction Stop
    Write-Output "Opened $app"
}} catch {{
    # Try finding in Start Menu
    $startMenu = @(
        "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
        "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
    )
    $found = $false
    foreach ($path in $startMenu) {{
        $shortcuts = Get-ChildItem -Path $path -Filter "*$app*.lnk" -Recurse -ErrorAction SilentlyContinue
        if ($shortcuts) {{
            Start-Process $shortcuts[0].FullName
            Write-Output "Opened $($shortcuts[0].Name)"
            $found = $true
            break
        }}
    }}
    if (-not $found) {{
        # Try as UWP app
        $uwpApp = Get-AppxPackage | Where-Object {{ $_.Name -like "*$app*" }} | Select-Object -First 1
        if ($uwpApp) {{
            Start-Process "shell:AppsFolder\\$($uwpApp.PackageFamilyName)!App"
            Write-Output "Opened UWP app $($uwpApp.Name)"
        }} else {{
            throw "Application not found: $app"
        }}
    }}
}}
'''
        else:
            return {"success": False, "error": "No target specified"}

        return await self._run_powershell(script)

    async def close_app(self, app_name: str, force: bool = False) -> dict[str, Any]:
        """Close an application by name."""
        if force:
            script = f'Stop-Process -Name "{app_name}" -Force -ErrorAction SilentlyContinue; Write-Output "Force closed {app_name}"'
        else:
            script = f'''
$processes = Get-Process -Name "{app_name}" -ErrorAction SilentlyContinue
if ($processes) {{
    foreach ($proc in $processes) {{
        $proc.CloseMainWindow() | Out-Null
    }}
    Start-Sleep -Milliseconds 500
    # Check if still running
    $remaining = Get-Process -Name "{app_name}" -ErrorAction SilentlyContinue
    if ($remaining) {{
        Write-Output "Sent close signal to {app_name}, some instances may still be running"
    }} else {{
        Write-Output "Closed {app_name}"
    }}
}} else {{
    Write-Output "No process named {app_name} found"
}}
'''
        return await self._run_powershell(script)

    async def list_apps(self, limit: int = 20) -> dict[str, Any]:
        """List running applications with visible windows."""
        script = f'''
$apps = Get-Process | Where-Object {{ $_.MainWindowTitle -ne "" }} | 
    Select-Object -First {limit} -Property Name, MainWindowTitle, Id |
    ForEach-Object {{ "$($_.Name) - $($_.MainWindowTitle) (PID: $($_.Id))" }}
$apps -join "`n"
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            apps = [a.strip() for a in result.get("stdout", "").strip().split("\n") if a.strip()]
            return {"success": True, "apps": apps, "count": len(apps)}
        return result

    async def list_processes(self, filter_pattern: str | None = None, limit: int = 20) -> dict[str, Any]:
        """List running processes."""
        if filter_pattern:
            script = f'''
Get-Process | Where-Object {{ $_.Name -like "*{filter_pattern}*" -or $_.MainWindowTitle -like "*{filter_pattern}*" }} |
    Select-Object -First {limit} -Property Id, Name, CPU, @{{Name="Memory(MB)";Expression={{[math]::Round($_.WorkingSet64/1MB, 2)}}}} |
    Format-Table -AutoSize | Out-String
'''
        else:
            script = f'''
Get-Process | Sort-Object -Property CPU -Descending |
    Select-Object -First {limit} -Property Id, Name, CPU, @{{Name="Memory(MB)";Expression={{[math]::Round($_.WorkingSet64/1MB, 2)}}}} |
    Format-Table -AutoSize | Out-String
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            return {"success": True, "processes": result.get("stdout", ""), "raw": True}
        return result

    async def kill_process(self, target: str, force: bool = False) -> dict[str, Any]:
        """Kill a process by name or PID."""
        force_flag = "-Force" if force else ""
        if target.isdigit():
            script = f'Stop-Process -Id {target} {force_flag} -ErrorAction Stop; Write-Output "Killed process {target}"'
        else:
            script = f'Stop-Process -Name "{target}" {force_flag} -ErrorAction Stop; Write-Output "Killed process {target}"'
        return await self._run_powershell(script)

    async def get_system_info(self) -> dict[str, Any]:
        """Get Windows system information."""
        script = '''
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$mem = Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum

$info = @{
    "OS" = $os.Caption
    "Version" = $os.Version
    "Build" = $os.BuildNumber
    "Architecture" = $os.OSArchitecture
    "Computer" = $env:COMPUTERNAME
    "User" = $env:USERNAME
    "CPU" = $cpu.Name
    "Cores" = $cpu.NumberOfCores
    "RAM_GB" = [math]::Round($mem.Sum / 1GB, 2)
    "Uptime" = (Get-Date) - $os.LastBootUpTime | ForEach-Object { "$($_.Days)d $($_.Hours)h $($_.Minutes)m" }
}
$info | ConvertTo-Json
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            import json
            try:
                info = json.loads(result.get("stdout", "{}"))
                return {"success": True, "info": info}
            except json.JSONDecodeError:
                return {"success": True, "info": {"raw": result.get("stdout", "")}}
        return result

    async def search_files(self, pattern: str, path: str = ".", recursive: bool = True) -> dict[str, Any]:
        """Search for files matching a pattern."""
        recurse_flag = "-Recurse" if recursive else ""
        script = f'''
Get-ChildItem -Path "{path}" {recurse_flag} -Filter "*{pattern}*" -File -ErrorAction SilentlyContinue |
    Select-Object -First 50 -ExpandProperty FullName
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            files = [f.strip() for f in result.get("stdout", "").strip().split("\n") if f.strip()]
            return {"success": True, "files": files, "count": len(files)}
        return result

    async def send_keys(self, keys: str) -> dict[str, Any]:
        """Send keystrokes to the active window using SendKeys."""
        # Escape special characters for SendKeys
        script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{keys}")
Write-Output "Sent keys: {keys}"
'''
        return await self._run_powershell(script)

    async def type_text(self, text: str) -> dict[str, Any]:
        """Type text into the active window."""
        # Escape special SendKeys characters
        escaped = text.replace("+", "{+}").replace("^", "{^}").replace("%", "{%}").replace("~", "{~}")
        escaped = escaped.replace("(", "{(}").replace(")", "{)}").replace("[", "{[}").replace("]", "{]}")
        escaped = escaped.replace("{", "{{").replace("}", "}}")
        return await self.send_keys(escaped)

    async def press_key(self, key: str) -> dict[str, Any]:
        """Press a special key."""
        # Map common key names to SendKeys format
        key_map = {
            "enter": "~",
            "return": "~",
            "tab": "{TAB}",
            "escape": "{ESC}",
            "esc": "{ESC}",
            "backspace": "{BACKSPACE}",
            "delete": "{DELETE}",
            "up": "{UP}",
            "down": "{DOWN}",
            "left": "{LEFT}",
            "right": "{RIGHT}",
            "home": "{HOME}",
            "end": "{END}",
            "pageup": "{PGUP}",
            "pagedown": "{PGDN}",
            "f1": "{F1}", "f2": "{F2}", "f3": "{F3}", "f4": "{F4}",
            "f5": "{F5}", "f6": "{F6}", "f7": "{F7}", "f8": "{F8}",
            "f9": "{F9}", "f10": "{F10}", "f11": "{F11}", "f12": "{F12}",
        }
        send_key = key_map.get(key.lower(), key)
        return await self.send_keys(send_key)

    async def get_active_window(self) -> dict[str, Any]:
        """Get information about the currently active window."""
        script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$hwnd = [Win32]::GetForegroundWindow()
$title = New-Object System.Text.StringBuilder 256
[Win32]::GetWindowText($hwnd, $title, 256) | Out-Null
$processId = 0
[Win32]::GetWindowThreadProcessId($hwnd, [ref]$processId) | Out-Null
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue

@{
    "Title" = $title.ToString()
    "ProcessName" = $process.Name
    "ProcessId" = $processId
    "Handle" = $hwnd.ToInt64()
} | ConvertTo-Json
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            import json
            try:
                info = json.loads(result.get("stdout", "{}"))
                return {"success": True, "window": info}
            except json.JSONDecodeError:
                return {"success": True, "window": {"raw": result.get("stdout", "")}}
        return result

    async def focus_window(self, title_or_process: str) -> dict[str, Any]:
        """Bring a window to the foreground by title or process name."""
        script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Focus {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@

$target = "{title_or_process}"
# Try by process name first
$proc = Get-Process -Name $target -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
if ($proc) {{
    [Win32Focus]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
    [Win32Focus]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
    Write-Output "Focused window: $($proc.MainWindowTitle)"
}} else {{
    # Try by window title
    $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*$target*" }} | Select-Object -First 1
    if ($proc) {{
        [Win32Focus]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
        [Win32Focus]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
        Write-Output "Focused window: $($proc.MainWindowTitle)"
    }} else {{
        throw "Window not found: $target"
    }}
}}
'''
        return await self._run_powershell(script)

    async def minimize_window(self, title_or_process: str | None = None) -> dict[str, Any]:
        """Minimize a window or the active window."""
        if title_or_process:
            script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Min {{
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
$proc = Get-Process -Name "{title_or_process}" -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
if (-not $proc) {{
    $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{title_or_process}*" }} | Select-Object -First 1
}}
if ($proc) {{
    [Win32Min]::ShowWindow($proc.MainWindowHandle, 6) | Out-Null  # SW_MINIMIZE
    Write-Output "Minimized: $($proc.MainWindowTitle)"
}} else {{
    throw "Window not found"
}}
'''
        else:
            script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32MinActive {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
$hwnd = [Win32MinActive]::GetForegroundWindow()
[Win32MinActive]::ShowWindow($hwnd, 6) | Out-Null
Write-Output "Minimized active window"
'''
        return await self._run_powershell(script)

    async def maximize_window(self, title_or_process: str | None = None) -> dict[str, Any]:
        """Maximize a window or the active window."""
        if title_or_process:
            script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Max {{
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
$proc = Get-Process -Name "{title_or_process}" -ErrorAction SilentlyContinue | Where-Object {{ $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
if (-not $proc) {{
    $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{title_or_process}*" }} | Select-Object -First 1
}}
if ($proc) {{
    [Win32Max]::ShowWindow($proc.MainWindowHandle, 3) | Out-Null  # SW_MAXIMIZE
    Write-Output "Maximized: $($proc.MainWindowTitle)"
}} else {{
    throw "Window not found"
}}
'''
        else:
            script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32MaxActive {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@
$hwnd = [Win32MaxActive]::GetForegroundWindow()
[Win32MaxActive]::ShowWindow($hwnd, 3) | Out-Null
Write-Output "Maximized active window"
'''
        return await self._run_powershell(script)

    async def take_screenshot(self, path: str | None = None) -> dict[str, Any]:
        """Take a screenshot of the entire screen."""
        import os
        if not path:
            path = os.path.join(os.environ.get("TEMP", "."), "screenshot.png")
        
        script = f'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$screens = [System.Windows.Forms.Screen]::AllScreens
$top = ($screens | ForEach-Object {{ $_.Bounds.Top }} | Measure-Object -Minimum).Minimum
$left = ($screens | ForEach-Object {{ $_.Bounds.Left }} | Measure-Object -Minimum).Minimum
$width = ($screens | ForEach-Object {{ $_.Bounds.Right }} | Measure-Object -Maximum).Maximum - $left
$height = ($screens | ForEach-Object {{ $_.Bounds.Bottom }} | Measure-Object -Maximum).Maximum - $top

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($left, $top, 0, 0, $bitmap.Size)
$bitmap.Save("{path}")
$graphics.Dispose()
$bitmap.Dispose()
Write-Output "Screenshot saved to {path}"
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            return {"success": True, "path": path, "message": result.get("stdout", "")}
        return result

    async def get_clipboard(self) -> dict[str, Any]:
        """Get clipboard content."""
        script = '''
Add-Type -AssemblyName System.Windows.Forms
$clip = [System.Windows.Forms.Clipboard]::GetText()
if ($clip) {
    Write-Output $clip
} else {
    Write-Output "[Clipboard is empty or contains non-text data]"
}
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            return {"success": True, "content": result.get("stdout", "").strip()}
        return result

    async def set_clipboard(self, text: str) -> dict[str, Any]:
        """Set clipboard content."""
        # Escape for PowerShell
        escaped = text.replace("'", "''")
        script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Clipboard]::SetText('{escaped}')
Write-Output "Clipboard set"
'''
        return await self._run_powershell(script)

    async def show_notification(self, title: str, message: str) -> dict[str, Any]:
        """Show a Windows toast notification."""
        script = f'''
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
    <visual>
        <binding template="ToastText02">
            <text id="1">{title}</text>
            <text id="2">{message}</text>
        </binding>
    </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("LangTARS")
$notifier.Show($toast)
Write-Output "Notification shown"
'''
        return await self._run_powershell(script)

    async def run_as_admin(self, command: str) -> dict[str, Any]:
        """Run a command with administrator privileges (will prompt UAC)."""
        script = f'''
Start-Process powershell -Verb RunAs -ArgumentList '-Command', '{command.replace("'", "''")}'
Write-Output "Launched elevated process"
'''
        return await self._run_powershell(script)
