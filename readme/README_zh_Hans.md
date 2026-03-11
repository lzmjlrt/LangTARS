<p align="center">
  <img src="assets/icon.svg" alt="LangTARS" width="128">
</p>

<p align="center">
  <strong>LangTARS</strong> — LangBot 原生插件
</p>

<p align="center">
  <a href="../README.md">English</a>&nbsp; • &nbsp;
  <a href="README_zh_Hant.md">繁體中文</a>&nbsp; • &nbsp;
  <a href="README_ja_JP.md">日本語</a>&nbsp; • &nbsp;
  <a href="https://github.com/langbot-app/LangTARS">GitHub</a>
</p>

> ⚠️ **注意**：功能仍在积极开发中，如遇 bug 请提交 [issue](https://github.com/langbot-app/LangTARS/issues)。


---

## 什么是 LangTARS？

LangTARS 是基于 **现代Agent** 的 ReAct 理念开发的 **LangBot 原生插件**，旨在为 LangBot 用户带来 **OpenClaw** 般的体验。它使您能够通过 IM 消息使用自主 AI 任务规划来控制您的 **Mac、Windows 电脑或 Linux 系统**。如同《星际穿越》中的 **塔斯(TARS)** 一样，为您忠诚工作。

与 [OpenClaw](https://github.com/openclaw/openclaw) 类似，LangTARS 允许 AI 助手在您的电脑上执行真实操作——但具有 LangBot 插件的简洁与优雅。

## 为什么选择 LangTARS？

[OpenClaw](https://github.com/openclaw/openclaw) 是一个具有远见卓识的出色项目。然而，运行如此复杂的软件并赋予其访问您数字生活的权限，需要您信任可能不完全理解的系统。

LangTARS 采用不同的方式：
- **原生 LangBot 集成** — 使用 Nanobot 内核直接在 LangBot 内运行
- **轻量级** — 最少的代码库，您可以直接理解和审计
- **自主规划** — 使用 ReAct 循环实现智能任务执行
- **安全优先** — 内置命令限制、工作区隔离和危险命令拦截

## 快速开始

> ⚠️ **注意**：目前只测试过包管理器的方式。

### 手动部署

| 步骤 | 操作 |
|:----:|------|
| 1 | 使用包管理器部署 LangBot：`uvx langbot@latest` |
| 2 | 按照[文档](https://docs.langbot.app/zh/usage/platforms/readme)配置机器人 |
| 3 | 在插件市场安装 LangTARS 插件 |
| 4 | 在 LangTARS 插件设置页，选择自己的模型和进行其他设置 |

> 📱 **推荐**：推荐在 **Telegram** 或 **钉钉** 平台使用 LangTARS，以获得最佳体验。 


## 首次设置 - 权限配置

### macOS 权限

首次使用前，需要授予一些权限：

#### AppleScript automation 权限
- 打开 **系统偏好设置** > **隐私与安全性** > **辅助功能**
- 点击左下角 🔒 解锁
- 添加 **Terminal** 或你的聊天应用 (如 WeChat, Telegram 等)

#### Safari JavaScript 权限 (可选)
- 打开 **Safari** > **设置** > **高级**
- 勾选 **允许 Apple Events 中的 JavaScript**

### Windows 权限

Windows 上 LangTARS 使用 PowerShell 和 UI Automation 进行系统控制，通常无需额外权限配置。

### Linux 权限

Linux 上 LangTARS 使用标准 shell 命令进行系统控制，通常无需额外权限配置。确保 `xdg-open` 可用以打开 URL 和应用程序。

## 使用方法

### `!tars <任务>` — AI 任务执行

只需描述您想要做的事情，AI 就会自主规划并执行任务。

**示例：**
- `!tars 打开 Safari，访问 langbot.app,抓取元素并且告诉我`
- `!tars 新建一个备忘录，标题和内容为你好`
- `!tars 帮我整理桌面上的文件`
- `!tars 把结果保存到文件`（如果有上次任务历史，会自动继续）

- <code><del>!tars 给我炒俩菜。</del></code>

> 💡 **提示**：如果有上次任务的对话历史，LangTARS 会自动基于之前的上下文继续执行。直接描述您想做的事情即可！

### 浏览器控制

LangTARS 支持多种浏览器控制方式：

**macOS:**
| 命令示例 | 浏览器 | 说明 |
|----------|--------|------|
| `!tars 访问 github.com` | Playwright (Chromium) | 默认方式，无需额外权限 |
| `!tars 打开 Safari 并访问 github` | Safari 浏览器 | 使用真实 Safari，需要 AppleScript 权限 |
| `!tars 打开 Chrome 并访问 github` | Chrome 浏览器 | 使用真实 Chrome，需要 AppleScript 权限 |

**Windows:**
| 命令示例 | 浏览器 | 说明 |
|----------|--------|------|
| `!tars 访问 github.com` | Playwright (Chromium) | 默认方式，无需额外权限 |
| `!tars 打开 Chrome 并访问 github` | Chrome 浏览器 | 使用真实 Chrome，通过 PowerShell/UI Automation |
| `!tars 打开 Edge 并访问 github` | Edge 浏览器 | 使用真实 Edge，通过 PowerShell/UI Automation |

**Linux:**
| 命令示例 | 浏览器 | 说明 |
|----------|--------|------|
| `!tars 访问 github.com` | Playwright (Chromium) | 默认方式，无需额外权限 |
| `!tars 打开 firefox 并访问 github` | Firefox 浏览器 | 使用 xdg-open 或直接命令 |

AI 将：
1. 理解您的请求
2. 规划必要的步骤
3. 使用 shell 命令、文件操作、应用控制等逐一执行
4. 返回结果

## 控制命令

| 命令 | 描述 |
|------|------|
| `!tars stop` | 停止当前正在运行的任务 |
| `!tars what` | 查看 agent 当前正在做什么 |
| `!tars reset` | 清空对话历史，开始全新任务 |
| `!tars yes` | 确认危险操作（如 rm、reboot 等） |
| `!tars no` | 取消并停止危险操作 |
| `!tars help` | 显示帮助 |

## 配置

通过 LangBot 的设置配置 LangTARS：

| 选项 | 描述 | 默认值 |
|------|------|--------|
| `allowed_users` | 允许控制此电脑的用户 ID | [] |
| `command_whitelist` | 允许的 shell 命令（留空 = 在限制下允许所有） | [] |
| `workspace_path` | 文件操作的工作区目录 | ~/.langtars |
| `sandbox_mode` | 沙箱模式，限制文件操作在工作区内。关闭后允许全局文件访问 | true |
| `enable_shell` | 启用 shell 命令执行 | true |
| `enable_process` | 启用进程管理 | true |
| `enable_file` | 启用文件操作 | true |
| `enable_app` | 启用应用控制 | true |
| `enable_applescript` | 启用 AppleScript 执行 (macOS) | true |
| `enable_powershell` | 启用 PowerShell 执行 (Windows) | true |
| `planner_max_iterations` | 最大 ReAct 循环迭代次数 | 5 |
| `planner_model_uuid` | 用于任务规划的 LLM 模型 | （第一个可用） |
| `planner_rate_limit_seconds` | LLM 调用之间的速率限制 | 1 |
| `planner_auto_load_mcp` | 自动加载 MCP 工具 | true |

## 安全特性

- **危险命令拦截** — 默认阻止 `rm -rf /` 等命令
- **工作区隔离** — 文件操作限制在配置的工作区
- **命令白名单** — 可选择限制为特定命令
- **用户访问控制** — 可选择限制为特定用户

## 架构

```
IM 消息 --> LangBot --> PlannerTool (ReAct 循环) --> 工具 --> 系统操作 (Mac/Windows/Linux)
```

- **PlannerTool** — 使用 LLM 进行自主任务规划的 ReAct 循环
- **工具注册表** — 从 MCP 服务器和插件动态加载工具
- **内置工具** — Shell、进程、文件、应用控制

## 许可证

[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)

本项目采用知识共享署名-非商业性使用-禁止演绎 4.0 国际许可协议。您可以在署名的前提下分享本项目，但不得用于商业目的，也不得在修改后发布。
