<p align="center">
  <img src="assets/icon.svg" alt="LangTARS" width="128">
</p>

<p align="center">
  <strong>LangTARS</strong> — LangBot 原生插件
</p>

<p align="center">
  <a href="../README.md">English</a>&nbsp; • &nbsp;
  <a href="README_zh_Hans.md">简体中文</a>&nbsp; • &nbsp;
  <a href="README_ja_JP.md">日本語</a>&nbsp; • &nbsp;
  <a href="https://github.com/langbot-app/LangTARS">GitHub</a>
</p>

> ⚠️ **注意**：功能仍在積極開發中，如遇 bug 請提交 [issue](https://github.com/langbot-app/LangTARS/issues)。


---

## 什麼是 LangTARS？

LangTARS 是基於 **現代Agent** 的 ReAct 理念開發的 **LangBot 原生插件**，旨在為 LangBot 用戶帶來 **OpenClaw** 般的體驗。它使您能夠透過 IM 訊息使用自主 AI 任務規劃來控制您的 **Mac、Windows 電腦或 Linux 系統**。如同《星際穿越》中的 **塔斯(TARS)** 一樣，為您忠誠工作。

與 [OpenClaw](https://github.com/openclaw/openclaw) 類似，LangTARS 允許 AI 助手在您的電腦上執行真實操作——但具有 LangBot 插件的簡潔與優雅。

## 為什麼選擇 LangTARS？

[OpenClaw](https://github.com/openclaw/openclaw) 是一個具有遠見卓識的出色專案。然而，執行如此複雜的軟體並賦予其訪問您數位生活的權限，需要您信任可能不完全理解的系統。

LangTARS 採用不同的方式：
- **原生 LangBot 整合** — 使用 Nanobot 核心直接在 LangBot 內執行
- **輕量級** — 最少的程式碼庫，您可以直接理解和審計
- **自主規劃** — 使用 ReAct 循環實現智慧任務執行
- **安全優先** — 內建命令限制、工作區隔離和危險命令攔截

## 快速開始

> ⚠️ **注意**：目前只測試過套件管理器的方式。

### 手動部署

| 步驟 | 操作 |
|:----:|------|
| 1 | 使用套件管理器部署 LangBot：`uvx langbot@latest` |
| 2 | 按照[文檔](https://docs.langbot.app/zh/usage/platforms/readme)配置機器人 |
| 3 | 在插件市場安裝 LangTARS 插件 |
| 4 | 在 LangTARS 插件設定頁，選擇自己的模型和進行其他設定 |

> 📱 **推薦**：推薦在 **Telegram** 或 **釘釘** 平台使用 LangTARS，以獲得最佳體驗。


## 首次設定 - 權限配置

### macOS 權限

首次使用前，需要授予一些權限：

#### AppleScript automation 權限
- 開啟 **系統偏好設定** > **隱私與安全性** > **輔助功能**
- 點擊左下角 🔒 解鎖
- 新增 **Terminal** 或您的聊天應用 (如 WeChat, Telegram 等)

#### Safari JavaScript 權限 (可選)
- 開啟 **Safari** > **設定** > **進階**
- 勾選 **允許 Apple Events 中的 JavaScript**

### Windows 權限

Windows 上 LangTARS 使用 PowerShell 和 UI Automation 進行系統控制，通常無需額外權限配置。

### Linux 權限

Linux 上 LangTARS 使用標準 shell 命令進行系統控制，通常無需額外權限配置。確保 `xdg-open` 可用以開啟 URL 和應用程式。

## 使用方法

### `!tars <任務>` — AI 任務執行

只需描述您想要做的事情，AI 就會自主規劃並執行任務。

**範例：**
- `!tars 開啟 Safari，訪問 langbot.app，擷取元素並告訴我`
- `!tars 新建一個備忘錄，標題和內容為你好`
- `!tars 幫我整理桌面上的檔案`
- `!tars 把結果儲存到檔案`（如果有上次任務歷史，會自動繼續）

- <code><del>!tars 給我炒倆菜。</del></code>

> 💡 **提示**：如果有上次任務的對話歷史，LangTARS 會自動基於之前的上下文繼續執行。直接描述您想做的事情即可！

### 瀏覽器控制

LangTARS 支援多種瀏覽器控制方式：

**macOS:**
| 命令範例 | 瀏覽器 | 說明 |
|----------|--------|------|
| `!tars 訪問 github.com` | Playwright (Chromium) | 預設方式，無需額外權限 |
| `!tars 開啟 Safari 並訪問 github` | Safari 瀏覽器 | 使用真實 Safari，需要 AppleScript 權限 |
| `!tars 開啟 Chrome 並訪問 github` | Chrome 瀏覽器 | 使用真實 Chrome，需要 AppleScript 權限 |

**Windows:**
| 命令範例 | 瀏覽器 | 說明 |
|----------|--------|------|
| `!tars 訪問 github.com` | Playwright (Chromium) | 預設方式，無需額外權限 |
| `!tars 開啟 Chrome 並訪問 github` | Chrome 瀏覽器 | 使用真實 Chrome，透過 PowerShell/UI Automation |
| `!tars 開啟 Edge 並訪問 github` | Edge 瀏覽器 | 使用真實 Edge，透過 PowerShell/UI Automation |

**Linux:**
| 命令範例 | 瀏覽器 | 說明 |
|----------|--------|------|
| `!tars 訪問 github.com` | Playwright (Chromium) | 預設方式，無需額外權限 |
| `!tars 開啟 firefox 並訪問 github` | Firefox 瀏覽器 | 使用 xdg-open 或直接命令 |

AI 將：
1. 理解您的請求
2. 規劃必要的步驟
3. 使用 shell 命令、檔案操作、應用控制等逐一執行
4. 傳回結果

## 控制命令

| 命令 | 描述 |
|------|------|
| `!tars stop` | 停止當前正在執行的任務 |
| `!tars what` | 查看 agent 當前正在做什麼 |
| `!tars reset` | 清空對話歷史，開始全新任務 |
| `!tars yes` | 確認危險操作（如 rm、reboot 等） |
| `!tars no` | 取消並停止危險操作 |
| `!tars help` | 顯示幫助 |

## 設定

透過 LangBot 的設定配置 LangTARS：

| 選項 | 描述 | 預設值 |
|------|------|--------|
| `allowed_users` | 允許控制此電腦的使用者 ID | [] |
| `command_whitelist` | 允許的 shell 命令（留空 = 在限制下允許所有） | [] |
| `workspace_path` | 檔案操作的工作區目錄 | ~/.langtars |
| `sandbox_mode` | 沙箱模式，限制檔案操作在工作區內。關閉後允許全域檔案存取 | true |
| `enable_shell` | 啟用 shell 命令執行 | true |
| `enable_process` | 啟用程序管理 | true |
| `enable_file` | 啟用檔案操作 | true |
| `enable_app` | 啟用應用控制 | true |
| `enable_applescript` | 啟用 AppleScript 執行 (macOS) | true |
| `enable_powershell` | 啟用 PowerShell 執行 (Windows) | true |
| `planner_max_iterations` | 最大 ReAct 循環迭代次數 | 5 |
| `planner_model_uuid` | 用於任務規劃的 LLM 模型 | （第一個可用） |
| `planner_rate_limit_seconds` | LLM 呼叫之間的速率限制 | 1 |
| `planner_auto_load_mcp` | 自動載入 MCP 工具 | true |

## 安全特性

- **危險命令攔截** — 預設阻止 `rm -rf /` 等命令
- **工作區隔離** — 檔案操作限制在設定的工作區
- **命令白名單** — 可選擇限制為特定命令
- **使用者存取控制** — 可選擇限制為特定使用者

## 架構

```
IM 訊息 --> LangBot --> PlannerTool (ReAct 循環) --> 工具 --> 系統操作 (Mac/Windows/Linux)
```

- **PlannerTool** — 使用 LLM 進行自主任務規劃的 ReAct 循環
- **工具註冊表** — 從 MCP 伺服器和插件動態載入工具
- **內建工具** — Shell、程序、檔案、應用控制

## 授權

[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)

本專案採用創用 CC 姓名標示-非商業性-禁止改作 4.0 國際授權條款。您可在署名的前提下分享本專案，但不得用於商業目的，亦不得修改後發布。
