# Edge Control - Native Microsoft Edge browser control via PowerShell/COM

from __future__ import annotations

from typing import Any


class EdgeController:
    """Controller for native Microsoft Edge browser control on Windows."""

    def __init__(self, run_powershell_func):
        """Initialize with a function that executes PowerShell commands."""
        self._run_powershell = run_powershell_func

    async def open(self, url: str | None = None) -> dict[str, Any]:
        """Open Edge (optionally with URL)."""
        if url:
            return await self.navigate(url)

        script = 'Start-Process "msedge"'
        return await self._run_powershell(script)

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to URL in Edge."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        # Escape quotes for PowerShell
        url_escaped = url.replace('"', '`"')
        script = f'Start-Process "msedge" -ArgumentList "{url_escaped}"'
        return await self._run_powershell(script)

    async def new_tab(self, url: str = "about:blank") -> dict[str, Any]:
        """Open a new tab in Edge with the specified URL."""
        if not url.startswith(("http://", "https://", "about:")):
            url = "https://" + url
        
        # Use Edge's command line to open new tab
        url_escaped = url.replace('"', '`"')
        script = f'Start-Process "msedge" -ArgumentList "--new-tab", "{url_escaped}"'
        return await self._run_powershell(script)

    async def get_content(self) -> dict[str, Any]:
        """Get content from Edge using UI Automation."""
        script = '''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# Find Edge window
$edge = Get-Process -Name "msedge" -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1

if (-not $edge) {
    throw "Edge is not running or has no visible window"
}

$automation = [System.Windows.Automation.AutomationElement]::FromHandle($edge.MainWindowHandle)

# Get window title (usually contains page title)
$title = $automation.Current.Name

# Try to get URL from address bar
$addressBar = $automation.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    ))
)

$url = ""
if ($addressBar) {
    $valuePattern = $addressBar.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
    if ($valuePattern) {
        $url = $valuePattern.Current.Value
    }
}

@{
    "Title" = $title
    "URL" = $url
    "Note" = "For full page content, use Playwright browser automation"
} | ConvertTo-Json
'''
        result = await self._run_powershell(script)
        if result.get("success"):
            import json
            try:
                info = json.loads(result.get("stdout", "{}"))
                return {"success": True, "text": f"Title: {info.get('Title', '')}, URL: {info.get('URL', '')}", "info": info}
            except json.JSONDecodeError:
                return {"success": True, "text": result.get("stdout", "")}
        return result

    async def click(self, selector: str) -> dict[str, Any]:
        """Click element in Edge - requires Playwright for CSS selectors."""
        return {
            "success": False,
            "error": "CSS selector clicking requires Playwright browser automation. Use browser_click instead.",
            "suggestion": "For native Edge control, use focus_and_click with coordinates or keyboard navigation."
        }

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        """Type text into element in Edge - requires Playwright for CSS selectors."""
        return {
            "success": False,
            "error": "CSS selector typing requires Playwright browser automation. Use browser_type instead.",
            "suggestion": "For native Edge control, use focus_and_type to type into the focused element."
        }

    async def focus_and_type(self, text: str) -> dict[str, Any]:
        """Type text into the currently focused element in Edge."""
        # First ensure Edge is focused
        focus_script = '''
$edge = Get-Process -Name "msedge" -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1
if ($edge) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Edge {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    [Win32Edge]::SetForegroundWindow($edge.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 100
}
'''
        await self._run_powershell(focus_script)
        
        # Now type the text using SendKeys
        escaped = text.replace("+", "{+}").replace("^", "{^}").replace("%", "{%}").replace("~", "{~}")
        escaped = escaped.replace("(", "{(}").replace(")", "{)}").replace("[", "{[}").replace("]", "{]}")
        escaped = escaped.replace("{", "{{").replace("}", "}}")
        
        type_script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{escaped}")
Write-Output "Typed text into Edge"
'''
        return await self._run_powershell(type_script)

    async def press_key(self, key: str) -> dict[str, Any]:
        """Press key in Edge."""
        # First ensure Edge is focused
        focus_script = '''
$edge = Get-Process -Name "msedge" -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1
if ($edge) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32EdgeKey {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    [Win32EdgeKey]::SetForegroundWindow($edge.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 100
}
'''
        await self._run_powershell(focus_script)
        
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
            # Ctrl combinations
            "ctrl+a": "^a", "ctrl+c": "^c", "ctrl+v": "^v", "ctrl+x": "^x",
            "ctrl+z": "^z", "ctrl+y": "^y", "ctrl+s": "^s", "ctrl+f": "^f",
            "ctrl+t": "^t", "ctrl+w": "^w", "ctrl+n": "^n", "ctrl+l": "^l",
            # Alt combinations
            "alt+f4": "%{F4}", "alt+tab": "%{TAB}",
        }
        send_key = key_map.get(key.lower(), key)
        
        key_script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{send_key}")
Write-Output "Pressed key: {key}"
'''
        return await self._run_powershell(key_script)

    async def go_back(self) -> dict[str, Any]:
        """Navigate back in Edge."""
        return await self.press_key("alt+left")

    async def go_forward(self) -> dict[str, Any]:
        """Navigate forward in Edge."""
        return await self.press_key("alt+right")

    async def refresh(self) -> dict[str, Any]:
        """Refresh the current page in Edge."""
        return await self.press_key("f5")

    async def close_tab(self) -> dict[str, Any]:
        """Close the current tab in Edge."""
        return await self.press_key("ctrl+w")

    async def focus_address_bar(self) -> dict[str, Any]:
        """Focus the address bar in Edge."""
        return await self.press_key("ctrl+l")

    async def search(self, query: str) -> dict[str, Any]:
        """Search in Edge using the address bar."""
        # Focus address bar
        await self.focus_address_bar()
        
        # Wait a bit for focus
        import asyncio
        await asyncio.sleep(0.2)
        
        # Type the search query
        await self.focus_and_type(query)
        
        # Press Enter
        return await self.press_key("enter")

    async def scroll_down(self, amount: int = 3) -> dict[str, Any]:
        """Scroll down in Edge."""
        # Focus Edge first
        focus_script = '''
$edge = Get-Process -Name "msedge" -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1
if ($edge) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32EdgeScroll {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    [Win32EdgeScroll]::SetForegroundWindow($edge.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 100
}
'''
        await self._run_powershell(focus_script)
        
        # Send Page Down or multiple Down arrows
        keys = "{PGDN}" * amount
        scroll_script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{keys}")
Write-Output "Scrolled down"
'''
        return await self._run_powershell(scroll_script)

    async def scroll_up(self, amount: int = 3) -> dict[str, Any]:
        """Scroll up in Edge."""
        focus_script = '''
$edge = Get-Process -Name "msedge" -ErrorAction SilentlyContinue | 
    Where-Object { $_.MainWindowHandle -ne 0 } | 
    Select-Object -First 1
if ($edge) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32EdgeScrollUp {
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@
    [Win32EdgeScrollUp]::SetForegroundWindow($edge.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 100
}
'''
        await self._run_powershell(focus_script)
        
        keys = "{PGUP}" * amount
        scroll_script = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{keys}")
Write-Output "Scrolled up"
'''
        return await self._run_powershell(scroll_script)

    async def zoom_in(self) -> dict[str, Any]:
        """Zoom in on the page."""
        return await self.press_key("ctrl++")

    async def zoom_out(self) -> dict[str, Any]:
        """Zoom out on the page."""
        return await self.press_key("ctrl+-")

    async def reset_zoom(self) -> dict[str, Any]:
        """Reset zoom to 100%."""
        return await self.press_key("ctrl+0")

    async def open_dev_tools(self) -> dict[str, Any]:
        """Open Developer Tools in Edge."""
        return await self.press_key("f12")

    async def full_screen(self) -> dict[str, Any]:
        """Toggle full screen mode in Edge."""
        return await self.press_key("f11")
