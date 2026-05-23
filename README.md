# aicfg-sync

AI 编程工具配置同步工具 - 基于 iCloud Drive 实现跨 Mac 同步。

## 支持的工具

- **Claude Code** - 设置、Skills、Hooks、MCP、claude.md
- **Kimi Code CLI** - 配置、Skills、MCP
- **Codex CLI** - 配置、Skills、Hooks、AGENTS.md
- **OpenCode Desktop** - 全局设置、工作区设置

## 快速开始

### 1. 安装

```bash
cd ~/work/aicfg-sync
./install.sh
```

### 2. 初始化

```bash
aicfg-sync init
```

### 3. 同步配置

在公司电脑上：
```bash
aicfg-sync push
```

在笔记本上：
```bash
aicfg-sync pull
```

`push` 和 `pull` 默认已启用自动冲突解决（保留本地方/保留 iCloud 方），无需加 `-y`。

## 命令说明

| 命令 | 说明 |
|------|------|
| `aicfg-sync init` | 初始化同步配置 |
| `aicfg-sync push` | 推送本地配置到 iCloud |
| `aicfg-sync pull` | 从 iCloud 拉取配置到本地 |
| `aicfg-sync status` | 查看同步状态 |
| `aicfg-sync diff` | 对比本地与 iCloud 配置差异（JSON/TOML 结构化对比） |
| `aicfg-sync doctor` | 系统检查诊断（iCloud、状态、文件、备份） |
| `aicfg-sync check` | 检查 iCloud 是否有比本地新的内容 |
| `aicfg-sync rollback` | 交互式恢复备份 |
| `aicfg-sync edit` | 用 $EDITOR 打开 mapping.toml |
| `aicfg-sync push --history` | 同步全部历史记录 |
| `aicfg-sync push --history claude,kimi` | 按工具同步历史记录 |
| `aicfg-sync push --dry-run` | 模拟运行（不实际修改） |
| `aicfg-sync push -y` | 强制自动解决冲突（覆盖 mapping.toml 中的默认策略） |
| `aicfg-sync rollback --last` | 恢复到最近一次 pull 前的状态 |
| `aicfg-sync setup-auto-check` | 安装登录时自动检查更新的 launchd 任务 |

## 配置文件

编辑 `~/.aicfg-sync/mapping.toml` 自定义同步内容，或使用 `aicfg-sync edit` 快捷打开。

### 默认冲突策略

```toml
[settings]
push_default = "keep-local"   # push 时默认保留本地（等价于 push -y）
pull_default = "keep-icloud"  # pull 时默认保留 iCloud（等价于 pull -y）
merge_enabled = true          # 启用 JSON/TOML 语义合并
```

### 目录排除

```toml
[tools.claude]
files = [
    { source = "~/.claude/skills/", target = "claude/skills/", exclude = ["deprecated/", "*.tmp"] },
]
```

## 功能特性

### JSON/TOML 语义合并

两台机器分别给 `settings.json` 添加了不同的 MCP server → 自动合并，不触发冲突。只有修改了同一个 key 才进入交互式解决。

### 备份与回滚

每次 `pull` 前自动备份被覆盖的本地文件到 `~/.aicfg-sync/backups/`。使用 `aicfg-sync rollback` 可交互式选择恢复，`rollback --last` 恢复最近一次。自动保留最近 10 次备份。

### 差异对比

`aicfg-sync diff` 显示每个文件的具体差异：JSON/TOML 文件显示 key 级别的结构化差异，文本文件显示 unified diff。

### 自动检查

`aicfg-sync check` 检查 iCloud 上是否有比本地更新的内容。配合 `aicfg-sync setup-auto-check` 安装 launchd 任务，每次登录自动运行。

## 安全说明

- **绝不同步**敏感凭证文件（auth.json、.credentials.json、.env 等）
- `settings.local.json` 不同步（该文件属于本机覆盖配置）
- Pull 前自动备份本地文件到 `~/.aicfg-sync/backups/`
- 支持 dry-run 模式预览变更
- 支持 `aicfg-sync rollback` 恢复到任意历史备份

## 历史记录同步

历史文件较大，默认不同步。如需同步：

```bash
aicfg-sync push --history              # 同步所有工具的历史
aicfg-sync push --history claude       # 仅同步 Claude 的历史
aicfg-sync pull --history claude,kimi  # 同步 Claude 和 Kimi 的历史
```

## 工作原理

1. 读取 `mapping.toml` 中定义的文件映射（支持目录、符号链接、排除模式）
2. 计算文件 SHA256 哈希检测变更
3. 通过 iCloud Drive 的 `~/Library/Mobile Documents/com~apple~CloudDocs/AICfg-Sync/` 目录中转
4. JSON/TOML 文件尝试语义合并，非重叠 key 自动合并，重叠 key 进入冲突解决
5. 支持冲突检测和交互式/自动解决

## 注意事项

- 两台电脑需使用相同的 macOS 用户名
- iCloud Drive 需在两台电脑上登录同一 Apple ID
- 切换电脑后建议等待 iCloud 同步完成再执行 `pull`
- 使用 `aicfg-sync doctor` 排查同步异常
