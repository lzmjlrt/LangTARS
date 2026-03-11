<p align="center">
  <img src="assets/icon.svg" alt="LangTARS" width="128">
</p>

<p align="center">
  <strong>LangTARS</strong> — LangBot ネイティブプラグイン
</p>

<p align="center">
  <a href="../README.md">English</a>&nbsp; • &nbsp;
  <a href="README_zh_Hans.md">简体中文</a>&nbsp; • &nbsp;
  <a href="README_zh_Hant.md">繁體中文</a>&nbsp; • &nbsp;
  <a href="https://github.com/langbot-app/LangTARS">GitHub</a>
</p>

> ⚠️ **注意**: 機能は現在も開発中です。バグを発見した場合は、[issue](https://github.com/langbot-app/LangTARS/issues) を報告してください。


---

## LangTARS とは？

LangTARS は **モダンAgent** の ReAct コンセプトに基づいて開発された **LangBot ネイティブプラグイン**で、LangBot ユーザーに **OpenClaw** のような体験を提供します。IM メッセージを通じて自律的な AI タスクプランニングで **Mac、Windows PC、または Linux システム** を制御できます。《インターステラー》の **タース(TARS)** のように忠実にサービスを提供します。

[OpenClaw](https://github.com/openclaw/openclaw) と同様に、LangTARS は AI アシスタントがコンピュータで実際の操作を実行できますが、LangBot プラグインの洗練さと洗練さを備えています。

## なぜ LangTARS なのか？

[OpenClaw](https://github.com/openclaw/openclaw) は優れた先見的なプロジェクトです。しかし、そのような複雑なソフトウェアを実行し、デジタルライフへのアクセスを許可するには、十分に理解していないシステムを信頼する必要があります。

LangTARS は異なるアプローチを取ります：
- **ネイティブ LangBot 統合** — Nanobot カーネルを使用して LangBot 内で直接実行
- **軽量** — 最小のコードベースで、理解し監査可能
- **自律プランニング** — ReAct ループによるインテリジェントなタスク実行
- **セキュリティ第一** — 組み込みのコマンド制限、ワークスペース分離、危険なコマンド遮断

## クイックスタート

> ⚠️ **注意**：現在、パッケージマネージャー方式のみテスト済みです。

### 手動デプロイ

1. パッケージマネージャーで LangBot をデプロイ：
   ```bash
   uvx langbot@latest
   ```

2. [ドキュメント](https://docs.langbot.app/zh/usage/platforms/readme)に従ってボットを設定します。

> 📱 **おすすめ**：**Telegram** または **DingTalk（钉钉）** プラットフォームで LangTARS を使用することをおすすめします。

3. プラグインマーケットプレイスから LangTARS プラグインをインストールします。

4. LangTARS プラグイン設定ページで、モデルを選択し、その他の設定を行います。


## 初回セットアップ - 権限設定

### macOS 権限

初めて使用する前に、いくつかの権限を付与する必要があります：

#### AppleScript automation 権限
- **システム設定** > **プライバシーとセキュリティ** > **アクセシビリティ** を開く
- 左下の 🔒 をクリックしてロックを解除
- **ターミナル** やチャットアプリ（WeChat、Telegram など）を追加

#### Safari JavaScript 権限（オプション）
- **Safari** > **設定** > **詳細** を開く
- **Apple Events からの JavaScript を許可** にチェックを入れる

### Windows 権限

Windows では LangTARS は PowerShell と UI Automation を使用してシステムを制御します。通常、追加の権限設定は不要です。

### Linux 権限

Linux では LangTARS は標準シェルコマンドを使用してシステムを制御します。通常、追加の権限設定は不要です。URL やアプリケーションを開くために `xdg-open` が利用可能であることを確認してください。

## 使用方法

### `!tars <タスク>` — AI タスク実行

したいことを説明するだけで、AI が自律的にタスクをプランニングし実行します。

**例：**
- `!tars Safari を開いて、langbot.app にアクセスして、要素を取得して教えて`
- `!tars 新規メモを作成して、タイトルと内容を「こんにちは」にして`
- `!tars デスクトップのファイルを整理して`
- `!tars 結果をファイルに保存して`（前回のタスク履歴がある場合、自動的に続行）

- <code><del>!tars 料理を作ってください。</del></code>

> 💡 **ヒント**：前回のタスクの会話履歴がある場合、LangTARS は自動的に前のコンテキストに基づいて続行します。やりたいことを直接説明するだけです！

### ブラウザ制御

LangTARS は複数のブラウザ制御方法をサポートしています：

**macOS:**
| コマンド例 | ブラウザ | 説明 |
|----------|---------|------|
| `!tars github.com にアクセス` | Playwright (Chromium) | デフォルト、追加権限不要 |
| `!tars Safari を開いて github に行く` | Safari ブラウザ | 実際の Safari を使用、AppleScript 権限が必要 |
| `!tars Chrome を開いて github に行く` | Chrome ブラウザ | 実際の Chrome を使用、AppleScript 権限が必要 |

**Windows:**
| コマンド例 | ブラウザ | 説明 |
|----------|---------|------|
| `!tars github.com にアクセス` | Playwright (Chromium) | デフォルト、追加権限不要 |
| `!tars Chrome を開いて github に行く` | Chrome ブラウザ | 実際の Chrome を使用、PowerShell/UI Automation 経由 |
| `!tars Edge を開いて github に行く` | Edge ブラウザ | 実際の Edge を使用、PowerShell/UI Automation 経由 |

**Linux:**
| コマンド例 | ブラウザ | 説明 |
|----------|---------|------|
| `!tars github.com にアクセス` | Playwright (Chromium) | デフォルト、追加権限不要 |
| `!tars firefox を開いて github に行く` | Firefox ブラウザ | xdg-open または直接コマンドを使用 |

AI は以下を行います：
1. リクエストを理解する
2. 必要なステップをプランニングする
3. シェルコマンド、ファイル操作、アプリ制御などを使って一つずつ実行する
4. 結果を返す

## 制御コマンド

| コマンド | 説明 |
|---------|------|
| `!tars stop` | 現在実行中のタスクを停止 |
| `!tars what` | エージェントが今何をしているか表示 |
| `!tars reset` | 会話履歴をクリアして新しいタスクを開始 |
| `!tars yes` | 危険な操作を承認（rm、reboot など） |
| `!tars no` | 危険な操作をキャンセルして停止 |
| `!tars help` | ヘルプを表示 |

## 設定

LangBot の設定で LangTARS を構成：

| オプション | 説明 | デフォルト |
|-----------|------|------------|
| `allowed_users` | このコンピュータを制御できるユーザー ID | [] |
| `command_whitelist` | 許可するシェルコマンド（空 = 制限付きで全て許可） | [] |
| `workspace_path` | ファイル操作用のワークスペースディレクトリ | ~/.langtars |
| `sandbox_mode` | サンドボックスモード、ファイル操作をワークスペース内に制限。無効にするとグローバルファイルアクセスが可能 | true |
| `enable_shell` | シェルコマンド実行を有効化 | true |
| `enable_process` | プロセス管理を有効化 | true |
| `enable_file` | ファイル操作を有効化 | true |
| `enable_app` | アプリ制御を有効化 | true |
| `enable_applescript` | AppleScript 実行を有効化 (macOS) | true |
| `enable_powershell` | PowerShell 実行を有効化 (Windows) | true |
| `planner_max_iterations` | 最大 ReAct ループ反復回数 | 5 |
| `planner_model_uuid` | タスクプランニング用の LLM モデル | （最初の利用可能なモデル） |
| `planner_rate_limit_seconds` | LLM 呼び出し間のレート制限 | 1 |
| `planner_auto_load_mcp` | MCP ツールを自動読み込み | true |

## セキュリティ機能

- **危険コマンド遮断** — `rm -rf /` などのコマンドをデフォルトでブロック
- **ワークスペース分離** — ファイル操作を設定されたワークスペースに制限
- **コマンドホワイトリスト** — 特定のコマンドに制限可能
- **ユーザーアクセス制御** — 特定のユーザーに制限可能

## アーキテクチャ

```
IM メッセージ --> LangBot --> PlannerTool (ReAct ループ) --> ツール --> システム操作 (Mac/Windows/Linux)
```

- **PlannerTool** — LLM を使用した自律タスクプランニングの ReAct ループ
- **ツールレジストリ** — MCP サーバーとプラグインからツールを動的に読み込み
- **組み込みツール** — シェル、プロセス、ファイル、アプリ制御

## ライセンス

[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/)

本プロジェクトはクリエイティブ・コモンズ 表示-非営利-改変禁止 4.0 国際ライセンスの下で提供されています。帰属を明示すれば共有できますが、商業利用や改変後の再配布は禁止されています。
