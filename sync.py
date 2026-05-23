"""核心同步逻辑"""

import difflib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from icloud_backend import iCloudBackend
from mapping import SyncMapping, collect_files
from conflict import ConflictResolution, detect_conflict, resolve_conflict_interactive, try_semantic_merge


def _fmt(val, max_len=60):
    s = str(val)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def _structured_diff(local, icloud, prefix=""):
    lines = []
    if isinstance(local, dict) and isinstance(icloud, dict):
        all_keys = sorted(set(local.keys()) | set(icloud.keys()))
        for key in all_keys:
            full = f"{prefix}.{key}" if prefix else key
            if key not in icloud:
                lines.append(f"  - {full}: {_fmt(local[key])}  (仅在本地)")
            elif key not in local:
                lines.append(f"  + {full}: {_fmt(icloud[key])}  (仅在 iCloud)")
            elif local[key] == icloud[key]:
                continue
            elif isinstance(local[key], dict) and isinstance(icloud[key], dict):
                if prefix:
                    lines.append(f"  ~ {full}:")
                lines.extend(_structured_diff(local[key], icloud[key], full))
            else:
                lines.append(f"  ~ {full}:")
                lines.append(f"      本地: {_fmt(local[key])}")
                lines.append(f"      iCloud: {_fmt(icloud[key])}")
    else:
        if local != icloud:
            lines.append(f"  本地: {_fmt(local)}")
            lines.append(f"  iCloud: {_fmt(icloud)}")
    return lines


class SyncEngine:
    """同步引擎"""
    
    def __init__(self, backend: iCloudBackend, dry_run: bool = False):
        self.backend = backend
        self.dry_run = dry_run
    
    def push(self, mapping: SyncMapping, include_history=False, auto_resolve: bool = False) -> dict:
        """推送本地配置到 iCloud Drive"""
        if not auto_resolve and mapping.settings.get("push_default") == "keep-local":
            auto_resolve = True

        stats = {"uploaded": 0, "skipped": 0, "failed": 0, "conflicts": 0}

        print(f"{'='*60}")
        print("开始推送配置到 iCloud Drive...")
        print(f"{'='*60}")
        
        local_state = self.backend.load_state(local=True)
        icloud_state = self.backend.load_state(local=False)

        files = collect_files(mapping, include_history=include_history, check_exists=True)

        for section_name, tool_id, file_mapping, local_path, is_dir in files:
            relative_target = file_mapping.target

            current_state = self.backend.get_file_state(local_path)
            state_key = f"{section_name}:{tool_id}:{relative_target}"
            
            icloud_path = self.backend.get_target_path(relative_target)
            if icloud_path.exists():
                icloud_current_state = self.backend.get_file_state(icloud_path)
                last_sync = icloud_state.get("files", {}).get(state_key)
                
                conflict = detect_conflict(
                    local_path, icloud_path,
                    current_state, icloud_current_state,
                    last_sync,
                )
                
                if conflict:
                    if not self.dry_run and try_semantic_merge(local_path, icloud_path):
                        print(f"  🔀 语义合并: {relative_target}")
                        current_state = self.backend.get_file_state(local_path)
                        icloud_state["files"][state_key] = current_state
                        local_state["files"][state_key] = current_state
                        stats["uploaded"] += 1
                        continue

                    stats["conflicts"] += 1
                    if auto_resolve:
                        resolution = ConflictResolution.KEEP_LOCAL
                        print(f"  ⚠️  冲突自动解决（保留本地）: {relative_target}")
                    else:
                        resolution = resolve_conflict_interactive(conflict)

                    if resolution == ConflictResolution.KEEP_LOCAL:
                        pass
                    elif resolution == ConflictResolution.KEEP_ICLOUD:
                        print(f"  ⏭️  跳过（保留 iCloud）: {relative_target}")
                        stats["skipped"] += 1
                        continue
                    elif resolution == ConflictResolution.KEEP_BOTH:
                        backup_path = icloud_path.with_suffix(icloud_path.suffix + ".icloud")
                        if not self.dry_run:
                            shutil.copy2(icloud_path, backup_path)
                        print(f"  💾 备份 iCloud 版本到: {backup_path.name}")
                    elif resolution == ConflictResolution.SKIP:
                        stats["skipped"] += 1
                        continue

            if self.dry_run:
                print(f"  [DRY-RUN] 将上传: {relative_target}")
                stats["uploaded"] += 1
                continue
            
            print(f"  ⬆️  上传: {relative_target}")
            if self.backend.copy_to_icloud(local_path, relative_target, file_mapping.exclude):
                icloud_state["files"][state_key] = current_state
                local_state["files"][state_key] = current_state
                stats["uploaded"] += 1
            else:
                stats["failed"] += 1

        if not self.dry_run:
            icloud_state["last_sync"] = datetime.now().isoformat()
            local_state["last_sync"] = datetime.now().isoformat()
            self.backend.save_state(icloud_state, local=False)
            self.backend.save_state(local_state, local=True)
        
        self._print_stats(stats, "推送")
        return stats
    
    def pull(self, mapping: SyncMapping, include_history=False, auto_resolve: bool = False) -> dict:
        """从 iCloud Drive 拉取配置到本地"""
        if not auto_resolve and mapping.settings.get("pull_default") == "keep-icloud":
            auto_resolve = True

        stats = {"downloaded": 0, "skipped": 0, "failed": 0, "conflicts": 0, "unchanged": 0}

        print(f"{'='*60}")
        print("开始从 iCloud Drive 拉取配置...")
        print(f"{'='*60}")
        
        local_state = self.backend.load_state(local=True)
        icloud_state = self.backend.load_state(local=False)

        files = collect_files(mapping, include_history=include_history, check_exists=False)

        for section_name, tool_id, file_mapping, local_path, is_dir in files:
            relative_target = file_mapping.target
            self._pull_single_file(
                section_name, tool_id, file_mapping, local_path, relative_target,
                local_state, icloud_state, stats, auto_resolve
            )

        if not self.dry_run:
            local_state["last_sync"] = datetime.now().isoformat()
            icloud_state["last_sync"] = datetime.now().isoformat()
            self.backend.save_state(local_state, local=True)
            self.backend.save_state(icloud_state, local=False)
        
        self._print_stats(stats, "拉取")
        if stats["downloaded"] > 0:
            print("\n💡 提示: Claude Code / Codex / OpenCode 在运行中，建议重启以加载新配置")
        return stats
    
    def _pull_single_file(self, section_name, tool_id, file_mapping, local_path, relative_target,
                          local_state, icloud_state, stats, auto_resolve):
        """拉取单个文件/目录"""
        icloud_path = self.backend.get_target_path(relative_target)
        state_key = f"{section_name}:{tool_id}:{relative_target}"
        
        if not icloud_path.exists():
            return
        
        icloud_current_state = self.backend.get_file_state(icloud_path)
        last_sync = local_state.get("files", {}).get(state_key)

        if local_path.exists():
            local_current_state = self.backend.get_file_state(local_path)

            if local_current_state["hash"] == icloud_current_state["hash"]:
                stats["unchanged"] += 1
                return

            conflict = detect_conflict(
                local_path, icloud_path,
                local_current_state, icloud_current_state,
                last_sync,
            )
            
            if conflict:
                if not self.dry_run and try_semantic_merge(local_path, icloud_path):
                    print(f"  🔀 语义合并: {relative_target}")
                    icloud_current_state = self.backend.get_file_state(icloud_path)
                    local_state["files"][state_key] = icloud_current_state
                    stats["downloaded"] += 1
                    return

                stats["conflicts"] += 1
                if auto_resolve:
                    resolution = ConflictResolution.KEEP_ICLOUD
                    print(f"  ⚠️  冲突自动解决（保留 iCloud）: {relative_target}")
                else:
                    resolution = resolve_conflict_interactive(conflict)

                if resolution == ConflictResolution.KEEP_LOCAL:
                    print(f"  ⏭️  跳过（保留本地）: {relative_target}")
                    stats["skipped"] += 1
                    return
                elif resolution == ConflictResolution.KEEP_ICLOUD:
                    pass
                elif resolution == ConflictResolution.KEEP_BOTH:
                    backup_path = local_path.with_suffix(local_path.suffix + ".local")
                    if not self.dry_run:
                        shutil.copy2(local_path, backup_path)
                    print(f"  💾 备份本地版本到: {backup_path.name}")
                elif resolution == ConflictResolution.SKIP:
                    stats["skipped"] += 1
                    return

        if local_path.exists() and not self.dry_run:
            backup_dir = Path.home() / ".aicfg-sync" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = backup_dir / timestamp
            session_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"{local_path.name}.bak"
            backup_path = session_dir / backup_name
            backup_map_path = session_dir / ".backup_map"
            try:
                if local_path.is_dir():
                    shutil.copytree(local_path, backup_path)
                else:
                    shutil.copy2(local_path, backup_path)
                backup_map = {}
                if backup_map_path.exists():
                    backup_map = json.loads(backup_map_path.read_text(encoding="utf-8"))
                backup_map[str(backup_path.relative_to(session_dir))] = str(local_path)
                backup_map_path.write_text(json.dumps(backup_map, ensure_ascii=False))
            except Exception:
                pass
        
        if self.dry_run:
            print(f"  [DRY-RUN] 将下载: {relative_target}")
            stats["downloaded"] += 1
            return
        
        print(f"  ⬇️  下载: {relative_target}")
        if self.backend.copy_from_icloud(relative_target, local_path, file_mapping.exclude):
            local_state["files"][state_key] = icloud_current_state
            stats["downloaded"] += 1
        else:
            stats["failed"] += 1
    
    def status(self, mapping: SyncMapping, include_history=False) -> dict:
        """查看同步状态"""
        print(f"{'='*60}")
        print("同步状态检查")
        print(f"{'='*60}")
        
        local_state = self.backend.load_state(local=True)
        icloud_state = self.backend.load_state(local=False)
        
        files = collect_files(mapping, include_history=include_history, check_exists=False)
        
        synced = 0
        pending_local = 0
        pending_icloud = 0
        conflict = 0
        missing = 0
        
        for section_name, tool_id, file_mapping, local_path, is_dir in files:
            relative_target = file_mapping.target
            icloud_path = self.backend.get_target_path(relative_target)
            state_key = f"{section_name}:{tool_id}:{relative_target}"
            
            if not local_path.exists() and not icloud_path.exists():
                missing += 1
                continue
            
            if not local_path.exists():
                pending_icloud += 1
                print(f"  ⬇️  仅 iCloud 有: {relative_target}")
                continue
            
            if not icloud_path.exists():
                pending_local += 1
                print(f"  ⬆️  仅本地有: {relative_target}")
                continue
            
            local_hash = self.backend.compute_hash(local_path)
            icloud_hash = self.backend.compute_hash(icloud_path)
            
            if local_hash == icloud_hash:
                synced += 1
            else:
                last_sync = local_state.get("files", {}).get(state_key, {}).get("hash")
                local_changed = local_hash != last_sync if last_sync else True
                icloud_changed = icloud_hash != last_sync if last_sync else True
                
                if local_changed and icloud_changed:
                    conflict += 1
                    print(f"  ⚠️  冲突: {relative_target}")
                elif local_changed:
                    pending_local += 1
                    print(f"  ⬆️  本地有更新: {relative_target}")
                else:
                    pending_icloud += 1
                    print(f"  ⬇️  iCloud 有更新: {relative_target}")
        
        print(f"{'='*60}")
        print(f"同步状态汇总:")
        print(f"  ✅ 已同步: {synced}")
        print(f"  ⬆️  待推送（本地更新）: {pending_local}")
        print(f"  ⬇️  待拉取（iCloud 更新）: {pending_icloud}")
        print(f"  ⚠️  冲突: {conflict}")
        print(f"  ❓ 缺失: {missing}")
        print(f"{'='*60}")
        
        return {
            "synced": synced,
            "pending_local": pending_local,
            "pending_icloud": pending_icloud,
            "conflict": conflict,
            "missing": missing,
        }
    
    def _print_stats(self, stats: dict, action: str):
        """打印同步统计"""
        print(f"{'='*60}")
        print(f"{action}完成!")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        print(f"{'='*60}")

    def diff(self, mapping: SyncMapping, include_history=False):
        print(f"{'='*60}")
        print("配置差异对比")
        print(f"{'='*60}")

        files = collect_files(mapping, include_history=include_history, check_exists=False)
        diff_count = 0

        for section_name, tool_id, file_mapping, local_path, is_dir in files:
            relative_target = file_mapping.target
            icloud_path = self.backend.get_target_path(relative_target)

            local_exists = local_path.exists()
            icloud_exists = icloud_path.exists()

            if not local_exists and not icloud_exists:
                continue

            if not local_exists:
                print(f"\n{'='*60}")
                print(f"📄 {relative_target}")
                print(f"{'='*60}")
                print("  仅 iCloud 有")
                diff_count += 1
                continue

            if not icloud_exists:
                print(f"\n{'='*60}")
                print(f"📄 {relative_target}")
                print(f"{'='*60}")
                print("  仅本地有")
                diff_count += 1
                continue

            if is_dir:
                local_hash = self.backend.compute_hash(local_path)
                icloud_hash = self.backend.compute_hash(icloud_path)
                if local_hash != icloud_hash:
                    print(f"\n{'='*60}")
                    print(f"📄 {relative_target}")
                    print(f"{'='*60}")
                    print("  目录内容不同，无法显示详细差异")
                    diff_count += 1
                continue

            local_hash = self.backend.compute_hash(local_path)
            icloud_hash = self.backend.compute_hash(icloud_path)
            if local_hash == icloud_hash:
                continue

            print(f"\n{'='*60}")
            print(f"📄 {relative_target}")
            print(f"{'='*60}")

            suffix = local_path.suffix.lower()
            if suffix in (".json", ".toml"):
                try:
                    if suffix == ".json":
                        with open(local_path, "r", encoding="utf-8") as f:
                            local_data = json.load(f)
                        with open(icloud_path, "r", encoding="utf-8") as f:
                            icloud_data = json.load(f)
                    else:
                        with open(local_path, "rb") as f:
                            local_data = tomllib.load(f)
                        with open(icloud_path, "rb") as f:
                            icloud_data = tomllib.load(f)
                    diffs = _structured_diff(local_data, icloud_data)
                    if diffs:
                        for line in diffs:
                            print(line)
                    else:
                        print("  (数据解析后无差异，仅格式不同)")
                except Exception:
                    self._show_text_diff(local_path, icloud_path)
            else:
                try:
                    self._show_text_diff(local_path, icloud_path)
                except (UnicodeDecodeError, Exception):
                    print("  内容不同（二进制或未知格式）")

            diff_count += 1

        print(f"\n{'='*60}")
        if diff_count == 0:
            print("✅ 所有文件内容相同")
        else:
            print(f"发现 {diff_count} 处差异")
        print(f"{'='*60}")

    @staticmethod
    def _show_text_diff(local_path: Path, icloud_path: Path):
        with open(local_path, "r", encoding="utf-8") as f:
            local_lines = f.readlines()
        with open(icloud_path, "r", encoding="utf-8") as f:
            icloud_lines = f.readlines()

        diff = difflib.unified_diff(
            local_lines, icloud_lines,
            fromfile=f"本地: {local_path}",
            tofile=f"iCloud: {icloud_path}",
            lineterm="",
        )
        for line in diff:
            print(f"  {line}")

    def rollback(self, backup_id=None):
        backup_dir = Path.home() / ".aicfg-sync" / "backups"
        if not backup_dir.exists():
            print("没有备份记录")
            return

        backups = sorted(
            [d for d in backup_dir.iterdir() if d.is_dir()],
            key=lambda p: p.name, reverse=True,
        )
        if not backups:
            print("没有备份记录")
            return

        if backup_id == "last":
            backup_id = backups[0].name

        if backup_id:
            target = backup_dir / backup_id
            if not target.exists():
                print(f"❌ 备份不存在: {backup_id}")
                return
            self._restore_backup(target)
            return

        print("可用备份:")
        for i, b in enumerate(backups):
            files = list(b.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            size = sum(f.stat().st_size for f in files if f.is_file())
            desc = f"  [{i}] {b.name} — {file_count} 个文件, {self._fmt_backup_size(size)}"
            if i == 0:
                desc += " (最新)"
            print(desc)

        print("\n输入编号恢复，或输入 'q' 取消:")
        try:
            choice = input("> ").strip()
            if choice.lower() == "q":
                return
            idx = int(choice)
            if 0 <= idx < len(backups):
                self._restore_backup(backups[idx])
            else:
                print("无效编号")
        except (ValueError, EOFError):
            print("已取消")

    def _restore_backup(self, backup_path: Path):
        print(f"正在恢复备份: {backup_path.name}")
        auto_clean = False
        for item in backup_path.iterdir():
            if item.name == ".backup_map":
                with open(item, "r", encoding="utf-8") as f:
                    backup_map = json.load(f)
                for relative, original in backup_map.items():
                    src = backup_path / relative
                    dst = Path(os.path.expanduser(original))
                    if src.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if src.is_dir():
                            if dst.exists():
                                shutil.rmtree(dst)
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                        print(f"  ✅ 已恢复: {original}")
                auto_clean = True
                break
        else:
            print("  ⚠️  无法确定备份来源，请手动恢复")
            return

        if auto_clean:
            self._auto_clean_backups(backup_path.parent)

    def _auto_clean_backups(self, backup_dir: Path, keep: int = 10):
        backups = sorted(
            [d for d in backup_dir.iterdir() if d.is_dir()],
            key=lambda p: p.name, reverse=True,
        )
        for old in backups[keep:]:
            shutil.rmtree(old)

    @staticmethod
    def _fmt_backup_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.0f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"

    def doctor(self):
        print("=" * 60)
        print("aicfg-sync 系统检查 (doctor)")
        print("=" * 60)

        ok, warn, err = 0, 0, 0

        icloud_base = iCloudBackend.ICLOUD_BASE
        if icloud_base.exists() and icloud_base.is_dir():
            print(f"✅ iCloud Drive 可用")
            ok += 1
        else:
            print(f"❌ iCloud Drive 不可用: {icloud_base}")
            err += 1

        sync_dir = icloud_base / iCloudBackend.SYNC_DIR_NAME
        if sync_dir.exists():
            file_count = sum(1 for f in sync_dir.rglob("*") if f.is_file())
            total_size = sum(f.stat().st_size for f in sync_dir.rglob("*") if f.is_file())
            print(f"✅ 同步目录存在 ({file_count} 个文件, {self._fmt_backup_size(total_size)})")
            ok += 1
        else:
            print(f"⚠️  同步目录不存在，运行 'aicfg-sync init' 创建")
            warn += 1

        local_state_path = Path.home() / ".aicfg-sync" / "local-state.json"
        if local_state_path.exists():
            try:
                state = json.loads(local_state_path.read_text(encoding="utf-8"))
                last_sync = state.get("last_sync", "从未同步")
                print(f"✅ 本地状态文件正常 (上次同步: {last_sync})")
                ok += 1
            except Exception:
                print(f"⚠️  本地状态文件损坏")
                warn += 1
        else:
            print(f"⚠️  本地状态文件不存在（可能尚未执行过同步）")
            warn += 1

        icloud_state = sync_dir / ".sync-state.json" if sync_dir.exists() else None
        if icloud_state and icloud_state.exists():
            try:
                state = json.loads(icloud_state.read_text(encoding="utf-8"))
                last_sync = state.get("last_sync", "从未同步")
                print(f"✅ iCloud 状态文件正常 (上次同步: {last_sync})")
                ok += 1
            except Exception:
                print(f"⚠️  iCloud 状态文件损坏")
                warn += 1
        else:
            print(f"⚠️  iCloud 状态文件不存在")
            warn += 1

        try:
            from mapping import load_mapping
            mapping = load_mapping()
            tool_count = len(mapping.tools)
            file_count = sum(len(t.files) for t in mapping.tools.values())
            history_count = len(mapping.history)
            print(f"✅ mapping.toml 有效 ({tool_count} 个工具, {file_count} 个文件, {history_count} 个历史记录)")
            ok += 1

            all_files = collect_files(mapping, include_history=True)
            missing_local = 0
            missing_icloud = 0
            large_files = []
            for _, _, fm, local_path, _ in all_files:
                if not local_path.exists():
                    missing_local += 1
                icloud_path = sync_dir / fm.target if sync_dir.exists() else None
                if icloud_path and not icloud_path.exists():
                    missing_icloud += 1
                if local_path.is_file():
                    size = local_path.stat().st_size
                    if size > 100 * 1024 * 1024:
                        large_files.append((fm.target, size))

            if missing_local > 0:
                print(f"⚠️  {missing_local} 个文件仅 iCloud 有（本地缺失）")
                warn += 1
            if missing_icloud > 0:
                print(f"⚠️  {missing_icloud} 个文件仅本地有（iCloud 缺失）")
                warn += 1
            if large_files:
                for name, size in large_files:
                    print(f"⚠️  大文件: {name} ({self._fmt_backup_size(size)})，同步可能很慢")
                    warn += 1
        except Exception as e:
            print(f"❌ mapping.toml 无效: {e}")
            err += 1

        backup_dir = Path.home() / ".aicfg-sync" / "backups"
        if backup_dir.exists():
            backups = [d for d in backup_dir.iterdir() if d.is_dir()]
            if backups:
                total_backup_size = sum(
                    sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
                    for b in backups
                )
                print(f"✅ 备份: {len(backups)} 次 ({self._fmt_backup_size(total_backup_size)})")
                ok += 1
                if len(backups) > 10:
                    print(f"💡 备份超过 10 次，下次 pull 将自动清理旧备份")

        print(f"\n{'=' * 60}")
        print(f"检查结果: {ok} 正常, {warn} 警告, {err} 错误")

    def check(self, mapping: SyncMapping, include_history=False):
        files = collect_files(mapping, include_history=include_history, check_exists=False)
        newer_on_icloud = 0

        for section_name, tool_id, file_mapping, local_path, is_dir in files:
            relative_target = file_mapping.target
            icloud_path = self.backend.get_target_path(relative_target)

            if not icloud_path.exists():
                continue

            if not local_path.exists():
                newer_on_icloud += 1
                print(f"  ⬇️  iCloud 有新文件: {relative_target}")
                continue

            local_mtime = local_path.stat().st_mtime
            icloud_mtime = icloud_path.stat().st_mtime

            if icloud_mtime > local_mtime:
                local_hash = self.backend.compute_hash(local_path)
                icloud_hash = self.backend.compute_hash(icloud_path)
                if local_hash != icloud_hash:
                    newer_on_icloud += 1
                    print(f"  ⬇️  iCloud 有更新: {relative_target}")

        if newer_on_icloud == 0:
            print("✅ 本地配置已是最新")
        else:
            print(f"\n💡 iCloud 上有 {newer_on_icloud} 个文件比本地新，运行 'aicfg-sync pull' 同步")

        return newer_on_icloud



