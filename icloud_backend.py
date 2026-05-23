"""iCloud Drive 存储后端"""

import fnmatch
import json
import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class iCloudBackend:
    """iCloud Drive 同步后端"""
    
    ICLOUD_BASE = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
    SYNC_DIR_NAME = "AICfg-Sync"
    
    def __init__(self, sync_dir_name: Optional[str] = None):
        self.sync_dir = self.ICLOUD_BASE / (sync_dir_name or self.SYNC_DIR_NAME)
        self.state_file = self.sync_dir / ".sync-state.json"
        self._ensure_sync_dir()
    
    def _ensure_sync_dir(self):
        """确保同步目录存在"""
        self.sync_dir.mkdir(parents=True, exist_ok=True)
    
    def get_target_path(self, relative_path: str) -> Path:
        """获取 iCloud 中的目标路径"""
        return self.sync_dir / relative_path
    
    def get_local_state_path(self) -> Path:
        """获取本地状态缓存路径"""
        return Path.home() / ".aicfg-sync" / "local-state.json"
    
    def compute_hash(self, file_path: Path) -> str:
        """计算文件 SHA256 哈希"""
        if file_path.is_dir():
            # 目录哈希：递归计算所有实际文件（非符号链接）的哈希组合
            hashes = []
            for f in sorted(file_path.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    hashes.append(self._file_hash(f))
            return hashlib.sha256("".join(hashes).encode()).hexdigest()[:16]
        else:
            return self._file_hash(file_path)[:16]
    
    def _file_hash(self, file_path: Path) -> str:
        """计算单个文件的 SHA256"""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    
    def get_file_state(self, file_path: Path) -> dict:
        """获取文件状态信息"""
        stat = file_path.stat()
        return {
            "hash": self.compute_hash(file_path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }
    
    def load_state(self, local: bool = False) -> Dict:
        """加载同步状态"""
        if local:
            state_path = self.get_local_state_path()
        else:
            state_path = self.state_file
        
        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"version": 1, "files": {}, "last_sync": None}
    
    def save_state(self, state: Dict, local: bool = False):
        """保存同步状态"""
        if local:
            state_path = self.get_local_state_path()
        else:
            state_path = self.state_file
        
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    
    def _copytree_with_symlinks(self, src: Path, dst: Path,
                                exclude_patterns: Optional[List[str]] = None):
        """复制目录，保留符号链接结构（不解析目标）"""
        dst.mkdir(parents=True, exist_ok=True)
        
        for item in src.iterdir():
            if exclude_patterns and _matches_pattern(item.name, exclude_patterns):
                continue
            dst_item = dst / item.name
            
            if item.is_symlink():
                if dst_item.exists() or dst_item.is_symlink():
                    dst_item.unlink()
                link_target = os.readlink(item)
                os.symlink(link_target, dst_item)
            elif item.is_dir():
                self._copytree_with_symlinks(item, dst_item, exclude_patterns)
            else:
                if dst_item.exists():
                    dst_item.unlink()
                shutil.copy2(item, dst_item)
    
    def copy_to_icloud(self, local_path: Path, relative_target: str,
                       exclude_patterns: Optional[List[str]] = None) -> bool:
        """将本地文件/目录复制到 iCloud Drive"""
        target_path = self.get_target_path(relative_target)
        
        try:
            if local_path.is_dir():
                if target_path.exists():
                    shutil.rmtree(target_path)
                self._copytree_with_symlinks(local_path, target_path, exclude_patterns)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path, target_path)
            return True
        except Exception as e:
            print(f"  ❌ 复制失败 {local_path} -> {target_path}: {e}")
            return False
    
    def copy_from_icloud(self, relative_source: str, local_path: Path,
                         exclude_patterns: Optional[List[str]] = None) -> bool:
        """从 iCloud Drive 复制到本地"""
        source_path = self.get_target_path(relative_source)
        
        if not source_path.exists():
            return False
        
        try:
            if source_path.is_dir():
                if local_path.exists():
                    shutil.rmtree(local_path)
                self._copytree_with_symlinks(source_path, local_path, exclude_patterns)
            else:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, local_path)
            return True
        except Exception as e:
            print(f"  ❌ 复制失败 {source_path} -> {local_path}: {e}")
            return False
    
    def list_synced_files(self) -> List[Tuple[str, Path]]:
        """列出 iCloud 中已同步的所有文件
        
        返回: [(relative_path, full_path), ...]
        """
        result = []
        if not self.sync_dir.exists():
            return result
        
        for path in self.sync_dir.rglob("*"):
            if path.name.startswith("."):
                continue
            relative = path.relative_to(self.sync_dir)
            result.append((str(relative), path))

        return result


def _matches_pattern(name: str, patterns: List[str]) -> bool:
    for pattern in patterns:
        clean = pattern.rstrip("/")
        if fnmatch.fnmatch(name, clean):
            return True
    return False
