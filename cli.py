#!/usr/bin/env python3
"""aicfg-sync CLI 入口"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from mapping import load_mapping
from icloud_backend import iCloudBackend
from sync import SyncEngine


def _load_mapping_or_die():
    try:
        return load_mapping()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        print("请先运行: aicfg-sync init")
        sys.exit(1)


def _build_engine(args):
    backend = iCloudBackend()
    return SyncEngine(backend, dry_run=getattr(args, "dry_run", False))


def _parse_history_arg(args):
    """解析 --history 参数，返回 False / True / [list]"""
    if not hasattr(args, "history") or args.history is None:
        return False
    if args.history == "all":
        return True
    return [t.strip() for t in args.history.split(",")]


def init_command(args):
    config_dir = Path.home() / ".aicfg-sync"
    config_dir.mkdir(parents=True, exist_ok=True)

    mapping_path = config_dir / "mapping.toml"

    if mapping_path.exists() and not args.force:
        print(f"配置文件已存在: {mapping_path}")
        print("使用 --force 覆盖")
        return

    template_path = Path(__file__).parent / "templates" / "mapping.toml"
    if template_path.exists():
        import shutil
        shutil.copy2(template_path, mapping_path)
        print(f"✅ 已创建默认配置: {mapping_path}")
    else:
        print(f"❌ 找不到默认模板: {template_path}")
        return

    icloud_base = iCloudBackend.ICLOUD_BASE
    if icloud_base.exists():
        print(f"✅ iCloud Drive 路径: {icloud_base}")
    else:
        print(f"⚠️  iCloud Drive 路径不存在: {icloud_base}")
        print("   请确保已登录 iCloud 并启用 iCloud Drive")

    sync_dir = icloud_base / iCloudBackend.SYNC_DIR_NAME
    sync_dir.mkdir(parents=True, exist_ok=True)
    print(f"✅ 同步目录: {sync_dir}")

    print("\n🎉 初始化完成!")
    print("   编辑 ~/.aicfg-sync/mapping.toml 自定义同步内容")
    print("   运行 'aicfg-sync status' 查看状态")


def push_command(args):
    mapping = _load_mapping_or_die()
    engine = _build_engine(args)
    engine.push(mapping, include_history=_parse_history_arg(args), auto_resolve=args.yes)


def pull_command(args):
    mapping = _load_mapping_or_die()
    engine = _build_engine(args)
    engine.pull(mapping, include_history=_parse_history_arg(args), auto_resolve=args.yes)


def status_command(args):
    mapping = _load_mapping_or_die()
    engine = SyncEngine(iCloudBackend())
    engine.status(mapping, include_history=_parse_history_arg(args))


def diff_command(args):
    mapping = _load_mapping_or_die()
    engine = SyncEngine(iCloudBackend())
    engine.diff(mapping, include_history=_parse_history_arg(args))


def rollback_command(args):
    engine = SyncEngine(iCloudBackend())
    engine.rollback(backup_id=args.backup)


def doctor_command(args):
    engine = SyncEngine(iCloudBackend())
    engine.doctor()


def edit_command(args):
    mapping_path = Path.home() / ".aicfg-sync" / "mapping.toml"
    if not mapping_path.exists():
        print("⚠️  配置文件不存在，请先运行: aicfg-sync init")
        sys.exit(1)
    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(mapping_path)])


def check_command(args):
    mapping = _load_mapping_or_die()
    engine = SyncEngine(iCloudBackend())
    engine.check(mapping, include_history=_parse_history_arg(args))


def setup_auto_check_command(args):
    plist_name = "com.aicfg-sync.check.plist"
    plist_path = Path.home() / "Library" / "LaunchAgents" / plist_name
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    script_path = Path.home() / ".local" / "bin" / "aicfg-sync"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.aicfg-sync.check</string>
    <key>ProgramArguments</key>
    <array>
        <string>{script_path}</string>
        <string>check</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{Path.home()}/.aicfg-sync/auto-check.log</string>
    <key>StandardErrorPath</key>
    <string>{Path.home()}/.aicfg-sync/auto-check.log</string>
</dict>
</plist>"""

    if plist_path.exists() and not args.force:
        print(f"⚠️  launchd 配置已存在: {plist_path}")
        print("   使用 --force 覆盖")
        return

    plist_path.write_text(plist_content)
    plist_path.chmod(0o644)
    print(f"✅ 已安装自动检查: {plist_path}")
    print(f"   每次登录时将自动运行 'aicfg-sync check'")
    print(f"   日志: ~/.aicfg-sync/auto-check.log")
    if args.force:
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
    print("   launchd 已加载")


def _add_history_arg(parser):
    parser.add_argument(
        "--history", nargs="?", const="all", default=None,
        help="包含历史记录。可指定工具: --history claude,kimi",
    )


def main():
    parser = argparse.ArgumentParser(
        prog="aicfg-sync",
        description="AI 编程工具配置同步工具 - 基于 iCloud Drive",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  aicfg-sync init              # 初始化配置
  aicfg-sync push              # 推送配置到 iCloud
  aicfg-sync pull              # 从 iCloud 拉取配置
  aicfg-sync status            # 查看同步状态
  aicfg-sync diff              # 对比配置差异
  aicfg-sync push --history    # 同步全部历史记录
  aicfg-sync push --history claude,kimi  # 按工具同步历史
  aicfg-sync pull --dry-run    # 模拟拉取（不实际修改）
  aicfg-sync doctor            # 系统检查
  aicfg-sync rollback --last   # 恢复到上次 pull 前的状态
  aicfg-sync check             # 检查 iCloud 是否有更新
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    init_parser = subparsers.add_parser("init", help="初始化同步配置")
    init_parser.add_argument("--force", action="store_true", help="强制覆盖现有配置")

    push_parser = subparsers.add_parser("push", help="推送本地配置到 iCloud Drive")
    _add_history_arg(push_parser)
    push_parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际修改")
    push_parser.add_argument("-y", "--yes", action="store_true", help="自动解决冲突（保留本地）")

    pull_parser = subparsers.add_parser("pull", help="从 iCloud Drive 拉取配置到本地")
    _add_history_arg(pull_parser)
    pull_parser.add_argument("--dry-run", action="store_true", help="模拟运行，不实际修改")
    pull_parser.add_argument("-y", "--yes", action="store_true", help="自动解决冲突（保留 iCloud）")

    diff_parser = subparsers.add_parser("diff", help="对比本地与 iCloud 配置差异")
    _add_history_arg(diff_parser)

    status_parser = subparsers.add_parser("status", help="查看同步状态")
    _add_history_arg(status_parser)

    rollback_parser = subparsers.add_parser("rollback", help="恢复备份")
    rollback_parser.add_argument("--last", dest="backup", action="store_const", const="last",
                                  help="恢复到最近一次备份")
    rollback_parser.add_argument("backup", nargs="?", default=None,
                                  help="备份 ID（不指定则交互式选择）")

    doctor_parser = subparsers.add_parser("doctor", help="系统检查诊断")

    edit_parser = subparsers.add_parser("edit", help="编辑 mapping.toml")

    check_parser = subparsers.add_parser("check", help="检查 iCloud 是否有新内容")
    _add_history_arg(check_parser)

    setup_check_parser = subparsers.add_parser("setup-auto-check", help="安装登录自动检查")
    setup_check_parser.add_argument("--force", action="store_true", help="强制覆盖现有配置")

    args = parser.parse_args()

    commands = {
        "init": init_command,
        "push": push_command,
        "pull": pull_command,
        "status": status_command,
        "diff": diff_command,
        "rollback": rollback_command,
        "doctor": doctor_command,
        "edit": edit_command,
        "check": check_command,
        "setup-auto-check": setup_auto_check_command,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
