<p align="center">
  <img src="assets/icon.svg" alt="LangTARS" width="128">
</p>

<p align="center">
  <strong>LangTARS</strong> — Native LangBot Plugin
</p>

<p align="center">
  <a href="readme/README_zh_Hans.md">简体中文</a>&nbsp; • &nbsp;
  <a href="readme/README_zh_Hant.md">繁體中文</a>&nbsp; • &nbsp;
  <a href="readme/README_ja_JP.md">日本語</a>&nbsp; • &nbsp;
  <a href="https://github.com/langbot-app/LangTARS">GitHub</a>
</p>

> ⚠️ **Note**: Features are still under active development. If you encounter any bugs, please submit an [issue](https://github.com/langbot-app/LangTARS/issues).


---

## What is LangTARS?

LangTARS is a **native LangBot plugin** developed based on the ReAct philosophy of **modern Agents**, designed to bring the **OpenClaw** experience to LangBot users. It enables you to control your **Mac, Windows PC, or Linux system** through IM messages using autonomous AI task planning. Like **TARS** from *Interstellar*, it works faithfully for you.

Like [OpenClaw](https://github.com/openclaw/openclaw), LangTARS allows AI assistants to execute real actions on your computer—but with the simplicity and elegance of a LangBot plugin.

## Why LangTARS?

[OpenClaw](https://github.com/openclaw/openclaw) is an impressive project with a great vision. However, running such complex software with access to your digital life requires trust in systems you may not fully understand.

LangTARS takes a different approach:
- **Native LangBot integration** — Runs directly within LangBot using the Nanobot kernel
- **Lightweight** — Minimal codebase you can understand and audit
- **Autonomous planning** — Uses ReAct loop for intelligent task execution
- **Safety-first** — Built-in command restrictions, workspace isolation, and dangerous command blocking

## Quick Start

> ⚠️ **Note**: Currently only the package manager method has been tested.

### Manual Deployment

| Step | Action |
|:----:|--------|
| 1 | Deploy LangBot using the package manager: `uvx langbot@latest` |
| 2 | Configure the bot following the [documentation](https://docs.langbot.app/en/usage/platforms/readme) |
| 3 | Install the LangTARS plugin from the plugin marketplace |
| 4 | In the LangTARS plugin settings page, select your model and configure other settings |

> 📱 **Recommended**: Use LangTARS on **Telegram** or **DingTalk** platform for the best experience.


## First-Time Setup - Permission Configuration

### macOS Permissions

Before first use, you need to grant some permissions:

#### AppleScript Automation Permission
- Open **System Preferences** > **Privacy & Security** > **Accessibility**
- Click the 🔒 in the bottom left to unlock
- Add **Terminal** or your chat application (e.g., WeChat, Telegram, etc.)

#### Safari JavaScript Permission (Optional)
- Open **Safari** > **Settings** > **Advanced**
- Check **Allow JavaScript from Apple Events**

### Windows Permissions

On Windows, LangTARS uses PowerShell and UI Automation for system control, typically no additional permission configuration is required.

### Linux Permissions

On Linux, LangTARS uses standard shell commands for system control, typically no additional permission configuration is required. Ensure `xdg-open` is available for opening URLs and applications.

## Usage

### `!tars <task>` — AI Task Execution

Simply describe what you want to do, and the AI will autonomously plan and execute the task.

**Examples:**
- `!tars Open Safari, visit langbot.app, scrape elements and tell me`
- `!tars Create a new note with title and content "hello"`
- `!tars Help me organize the files on my desktop`
- `!tars Save the result to a file` (continues from previous task if available)

- <code><del>!tars Cook me some dishes.</del></code>

> 💡 **Tip**: If you have a previous task history, LangTARS will automatically continue from where you left off. Just describe what you want to do next!

### Browser Control

LangTARS supports multiple browser control methods:

**macOS:**
| Command Example | Browser | Description |
|----------|---------|------|
| `!tars Visit github.com` | Playwright (Chromium) | Default, no extra permissions needed |
| `!tars Open Safari and visit github` | Safari Browser | Uses real Safari, requires AppleScript permission |
| `!tars Open Chrome and visit github` | Chrome Browser | Uses real Chrome, requires AppleScript permission |

**Windows:**
| Command Example | Browser | Description |
|----------|---------|------|
| `!tars Visit github.com` | Playwright (Chromium) | Default, no extra permissions needed |
| `!tars Open Chrome and visit github` | Chrome Browser | Uses real Chrome via PowerShell/UI Automation |
| `!tars Open Edge and visit github` | Edge Browser | Uses real Edge via PowerShell/UI Automation |

**Linux:**
| Command Example | Browser | Description |
|----------|---------|------|
| `!tars Visit github.com` | Playwright (Chromium) | Default, no extra permissions needed |
| `!tars Open firefox and visit github` | Firefox Browser | Uses xdg-open or direct command |

The AI will:
1. Understand your request
2. Plan the necessary steps
3. Execute them one by one using shell commands, file operations, app control, etc.
4. Report back with results

## Control Commands

| Command | Description |
|---------|-------------|
| `!tars stop` | Stop the currently running task |
| `!tars what` | What is the agent doing now |
| `!tars reset` | Clear conversation history and start fresh |
| `!tars yes` | Confirm dangerous operation (e.g., rm, reboot) |
| `!tars no` | Cancel and stop dangerous operation |
| `!tars help` | Show help |

## Configuration

Configure LangTARS through LangBot's settings:

| Option | Description | Default |
|--------|-------------|---------|
| `allowed_users` | User IDs allowed to control this computer | [] |
| `command_whitelist` | Allowed shell commands (empty = all with restrictions) | [] |
| `workspace_path` | Working directory for file operations | ~/.langtars |
| `sandbox_mode` | Restrict file operations to workspace only. When disabled, allows global file access | true |
| `enable_shell` | Enable shell command execution | true |
| `enable_process` | Enable process management | true |
| `enable_file` | Enable file operations | true |
| `enable_app` | Enable app control | true |
| `enable_applescript` | Enable AppleScript execution (macOS) | true |
| `enable_powershell` | Enable PowerShell execution (Windows) | true |
| `planner_max_iterations` | Max ReAct loop iterations | 5 |
| `planner_model_uuid` | LLM model for task planning | (first available) |
| `planner_rate_limit_seconds` | Rate limit between LLM calls | 1 |
| `planner_auto_load_mcp` | Auto-load MCP tools | true |

## Safety Features

- **Dangerous command blocking** — Commands like `rm -rf /` are blocked by default
- **Workspace isolation** — File operations restricted to configured workspace
- **Command whitelist** — Optionally restrict to specific commands
- **User access control** — Optionally limit to specific users

## Architecture

```
IM Message --> LangBot --> PlannerTool (ReAct Loop) --> Tools --> System Actions (Mac/Windows/Linux)
```

- **PlannerTool** — ReAct loop for autonomous task planning using LLM
- **Tool Registry** — Dynamic tool loading from MCP servers and plugins
- **Built-in Tools** — Shell, process, file, app control

## License

[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)

This project is licensed under the Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International License. You may share it with attribution, but you may not use it commercially or distribute modified versions.
