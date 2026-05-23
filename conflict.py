"""冲突检测与解决模块"""

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class ConflictResolution(Enum):
    """冲突解决策略"""
    KEEP_LOCAL = "local"      # 保留本地版本
    KEEP_ICLOUD = "icloud"    # 保留 iCloud 版本
    KEEP_BOTH = "both"        # 保留两个版本（重命名）
    SKIP = "skip"             # 跳过


@dataclass
class Conflict:
    """文件冲突信息"""
    relative_path: str
    local_path: Path
    icloud_path: Path
    local_state: dict
    icloud_state: dict
    last_sync_state: Optional[dict]
    
    def __str__(self) -> str:
        return f"冲突: {self.relative_path}\n  本地: {self.local_state}\n  iCloud: {self.icloud_state}"


def detect_conflict(
    local_path: Path,
    icloud_path: Path,
    local_state: dict,
    icloud_state: dict,
    last_sync_state: Optional[dict],
) -> Optional[Conflict]:
    """检测是否存在冲突
    
    冲突条件：
    1. 本地和 iCloud 都有该文件
    2. 本地和 iCloud 的哈希不同
    3. 本地和 iCloud 都与上次同步状态不同（即两边都修改了）
    """
    if not local_path.exists() or not icloud_path.exists():
        return None
    
    if local_state["hash"] == icloud_state["hash"]:
        return None  # 内容相同，无冲突
    
    # 如果有一边与上次同步状态相同，说明只有另一边修改了，不算冲突
    if last_sync_state:
        local_unchanged = local_state["hash"] == last_sync_state.get("hash")
        icloud_unchanged = icloud_state["hash"] == last_sync_state.get("hash")
        
        if local_unchanged and not icloud_unchanged:
            return None  # 只有 iCloud 修改了
        if icloud_unchanged and not local_unchanged:
            return None  # 只有本地修改了
    
    return Conflict(
        relative_path=str(icloud_path),
        local_path=local_path,
        icloud_path=icloud_path,
        local_state=local_state,
        icloud_state=icloud_state,
        last_sync_state=last_sync_state,
    )


def resolve_conflict_interactive(conflict: Conflict) -> ConflictResolution:
    """交互式解决冲突"""
    print(f"\n{'='*60}")
    print(f"发现冲突: {conflict.relative_path}")
    print(f"{'='*60}")
    print(f"  本地修改时间: {format_time(conflict.local_state.get('mtime'))}")
    print(f"  本地大小: {format_size(conflict.local_state.get('size', 0))}")
    print(f"  iCloud修改时间: {format_time(conflict.icloud_state.get('mtime'))}")
    print(f"  iCloud大小: {format_size(conflict.icloud_state.get('size', 0))}")
    print(f"{'='*60}")
    
    while True:
        print("\n请选择解决方式:")
        print("  [l] 保留本地版本 (local)")
        print("  [i] 保留 iCloud 版本 (icloud)")
        print("  [b] 保留两个版本，iCloud 版本重命名为 .icloud (both)")
        print("  [s] 跳过，暂不处理 (skip)")
        
        choice = input("你的选择 [l/i/b/s]: ").strip().lower()
        
        if choice in ("l", "local"):
            return ConflictResolution.KEEP_LOCAL
        elif choice in ("i", "icloud"):
            return ConflictResolution.KEEP_ICLOUD
        elif choice in ("b", "both"):
            return ConflictResolution.KEEP_BOTH
        elif choice in ("s", "skip"):
            return ConflictResolution.SKIP
        else:
            print("无效选择，请重新输入")


def format_time(timestamp) -> str:
    """格式化时间戳"""
    if timestamp is None:
        return "未知"
    from datetime import datetime
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(timestamp)


def format_size(size: int) -> str:
    """格式化文件大小"""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


def _deep_merge_dicts(local: Dict, icloud: Dict) -> Optional[Dict]:
    """深度合并两个字典。返回 None 表示存在无法自动解决的冲突。"""
    if not isinstance(local, dict) or not isinstance(icloud, dict):
        if local == icloud:
            return local
        return None

    result = {}
    all_keys = set(local.keys()) | set(icloud.keys())

    for key in all_keys:
        if key not in icloud:
            result[key] = local[key]
        elif key not in local:
            result[key] = icloud[key]
        else:
            lv = local[key]
            iv = icloud[key]
            if lv == iv:
                result[key] = lv
            elif isinstance(lv, dict) and isinstance(iv, dict):
                sub = _deep_merge_dicts(lv, iv)
                if sub is None:
                    return None
                result[key] = sub
            else:
                return None

    return result


def _dump_toml(data: dict, file_path: Path):
    """最小化 TOML 序列化器，仅处理 AI 配置文件中出现的常见类型。"""

    def _format(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        elif isinstance(v, (int, float)):
            return str(v)
        elif isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        elif isinstance(v, list):
            items = ", ".join(_format(i) for i in v)
            return f"[{items}]"
        elif v is None:
            return '""'
        return f'"{v}"'

    lines = []
    top_tables = {}
    top_values = {}
    for k, v in data.items():
        if isinstance(v, dict):
            top_tables[k] = v
        else:
            top_values[k] = v

    for k, v in top_values.items():
        lines.append(f"{k} = {_format(v)}")

    for section, table in top_tables.items():
        if lines:
            lines.append("")
        lines.append(f"[{section}]")
        for k, v in table.items():
            if isinstance(v, dict):
                lines.append("")
                lines.append(f"[{section}.{k}]")
                for sk, sv in v.items():
                    lines.append(f"{sk} = {_format(sv)}")
            else:
                lines.append(f"{k} = {_format(v)}")

    content = "\n".join(lines).lstrip() + "\n"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def try_semantic_merge(local_path: Path, icloud_path: Path) -> bool:
    """尝试对 JSON/TOML 文件进行语义合并。成功返回 True，失败返回 False。"""
    suffix = local_path.suffix.lower()
    if suffix not in (".json", ".toml"):
        return False

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

        merged = _deep_merge_dicts(local_data, icloud_data)
        if merged is None:
            return False

        if suffix == ".json":
            for path in (local_path, icloud_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(merged, f, indent=2, ensure_ascii=False)
                    f.write("\n")
        else:
            for path in (local_path, icloud_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                _dump_toml(merged, path)

        return True
    except Exception:
        return False
