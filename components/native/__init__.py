# Native - Native browser/system control modules
# macOS: Safari, Chrome (via AppleScript)
# Windows: Edge, Chrome, Windows system control (via PowerShell)

import platform

# Platform detection
IS_MACOS = platform.system() == "Darwin"
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

# Import platform-specific modules
if IS_MACOS:
    from .safari import SafariController
    from .chrome import ChromeController
elif IS_WINDOWS:
    from .windows import WindowsController
    from .edge import EdgeController
    from .chrome_windows import ChromeWindowsController
