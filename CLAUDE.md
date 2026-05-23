# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`aicfg-sync` — 基于 iCloud Drive 在多台 Mac 之间同步 AI 编程工具配置。Python 3.9+，零外部依赖。

## 命令

```bash
./install.sh                        # 安装到 ~/.local/bin/aicfg-sync
python3 cli.py init                 # 初始化（--force 覆盖）
python3 cli.py push                 # 推送本地 → iCloud（--history / --dry-run / -y）
python3 cli.py pull                 # 拉取 iCloud → 本地（--history / --dry-run / -y）
python3 cli.py status               # 查看同步状态（--history）
python3 cli.py diff                 # 对比差异（--history）
python3 cli.py doctor               # 系统诊断
python3 cli.py check                # 检查 iCloud 更新（--history）
python3 cli.py rollback             # 交互式恢复备份（--last）
python3 cli.py edit                 # 打开 $EDITOR 编辑 mapping.toml
python3 cli.py setup-auto-check     # 安装登录自动检查（--force）
```

## 架构

所有模块平铺在项目根目录，无嵌套包结构。

```
cli.py ──→ SyncEngine(sync.py) ──→ iCloudBackend(icloud_backend.py)
               │                        │
               ├──→ conflict.py         └──→ ~/Library/Mobile Documents/...CloudDocs/AICfg-Sync/
               └──→ mapping.py
```

| 模块 | 职责 |
|------|------|
| `cli.py` | argparse 入口，10 个子命令分发 |
| `sync.py` | `SyncEngine` — push/pull/status/diff/rollback/doctor/check、冲突委托、语义合并调用 |
| `icloud_backend.py` | `iCloudBackend` — iCloud Drive 文件 I/O、SHA256 哈希、JSON 状态持久化、目录复制（保留 symlink、支持 exclude） |
| `conflict.py` | `Conflict` 数据类 + `detect_conflict()` + 交互式解决 + `try_semantic_merge()` JSON/TOML 语义合并 |
| `mapping.py` | TOML 解析 → `SyncMapping`（含 `settings`）/`ToolMapping`/`FileMapping`（含 `exclude`）+ 敏感文件过滤 + `collect_files()` 支持按工具过滤历史 |
| `templates/mapping.toml` | 默认映射模板，含 `[settings]` 节定义默认冲突策略 |

### 数据流

1. `mapping.toml` 定义 `source → target` 映射 + `[settings]` 默认策略
2. `iCloudBackend` 操作 `~/Library/Mobile Documents/com~apple~CloudDocs/AICfg-Sync/`
3. 同步状态：`.sync-state.json`（iCloud 端）+ `~/.aicfg-sync/local-state.json`（本地缓存）
4. 冲突检测：两边 SHA256 与上次同步记录不同 → 先尝试语义合并（JSON/TOML deep merge）→ 失败再交互式解决
5. pull 时备份到 `~/.aicfg-sync/backups/<timestamp>/`（含 `.backup_map` 映射文件），rollback 恢复

### 关键设计点

- **保留符号链接**：`_copytree_with_symlinks()` 递归复制但不解引用 symlink，支持 exclude 模式过滤
- **敏感文件过滤**：`SENSITIVE_PATTERNS` 硬编码黑名单，`collect_files()` 始终生效
- **历史记录灵活控制**：`--history` 支持 `--history`（全部）/ `--history claude,kimi`（按工具过滤） / 不传（不同步）
- **语义合并**：`_deep_merge_dicts()` 对 JSON/TOML 做 key 级 deep merge，非重叠 key 自动合并避免假冲突
- **默认策略**：`mapping.toml` 的 `[settings]` 节可配置 push/pull 默认冲突策略，免去每次 `-y`
- **备份回滚**：pull 前自动备份到会话目录，`rollback --last` 快速恢复，自动清理保留 10 次
- **目录排除**：`FileMapping.exclude` 支持 fnmatch 通配符，目录同步时忽略匹配项
- **系统诊断**：`doctor` 检查 iCloud 可用性、状态文件完整性、文件缺失、大文件警告
- **自动检查**：`check` 命令 + `setup-auto-check` 安装 launchd plist 实现登录时自动检查更新
