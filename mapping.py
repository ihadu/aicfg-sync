"""配置映射解析模块"""

import os
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FileMapping:
    """单个文件/目录映射"""
    source: str  # 本地路径（支持 ~）
    target: str  # iCloud 中的相对路径
    sensitive: bool = False
    exclude: List[str] = field(default_factory=list)
    
    def resolved_source(self) -> Path:
        """解析 ~ 为 HOME 目录"""
        return Path(os.path.expanduser(self.source))


@dataclass
class ToolMapping:
    """单个工具的配置映射"""
    name: str
    files: List[FileMapping] = field(default_factory=list)


@dataclass
class SyncMapping:
    """完整的同步映射"""
    tools: Dict[str, ToolMapping] = field(default_factory=dict)
    history: Dict[str, ToolMapping] = field(default_factory=dict)
    settings: Dict[str, str] = field(default_factory=dict)


# 敏感文件模式（绝不同步）
SENSITIVE_PATTERNS = [
    "auth.json",
    ".credentials.json",
    "credentials/",
    "*.key",
    "*.pem",
    "*.p12",
    ".env",
    ".env.*",
]


def is_sensitive(path: Path) -> bool:
    """检查路径是否包含敏感信息"""
    path_str = str(path)
    name = path.name
    
    for pattern in SENSITIVE_PATTERNS:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif pattern.endswith("/"):
            if pattern.rstrip("/") in path.parts:
                return True
        else:
            if name == pattern:
                return True
    
    return False


def load_mapping(mapping_path: Optional[Path] = None) -> SyncMapping:
    """加载同步映射配置"""
    if mapping_path is None:
        mapping_path = Path.home() / ".aicfg-sync" / "mapping.toml"
    
    if not mapping_path.exists():
        # 使用默认模板
        template_path = Path(__file__).parent / "templates" / "mapping.toml"
        if template_path.exists():
            mapping_path = template_path
        else:
            raise FileNotFoundError(f"找不到映射配置文件: {mapping_path}")
    
    with open(mapping_path, "rb") as f:
        data = tomllib.load(f)
    
    mapping = SyncMapping()

    def _parse_section(section_data):
        result = {}
        for tool_id, tool_data in section_data.items():
            tool = ToolMapping(name=tool_data.get("name", tool_id))
            for file_data in tool_data.get("files", []):
                tool.files.append(FileMapping(
                    source=file_data["source"],
                    target=file_data["target"],
                    sensitive=file_data.get("sensitive", False),
                    exclude=file_data.get("exclude", []),
                ))
            result[tool_id] = tool
        return result

    mapping.tools = _parse_section(data.get("tools", {}))
    mapping.history = _parse_section(data.get("history", {}))
    mapping.settings = data.get("settings", {})
    return mapping


def collect_files(mapping: SyncMapping, include_history=False, check_exists: bool = True) -> List[tuple]:
    """收集所有需要同步的文件

    Args:
        mapping: 同步映射配置
        include_history: False=不同步历史, True=同步全部历史, list=只同步指定工具（如 ['claude']）
        check_exists: 是否跳过不存在的本地文件

    返回: [(section_name, tool_id, file_mapping, local_path, is_dir), ...]
    """
    result = []

    sections = [("tools", mapping.tools)]
    if include_history:
        history_section = mapping.history
        if isinstance(include_history, list):
            history_section = {k: v for k, v in mapping.history.items() if k in include_history}
        sections.append(("history", history_section))
    
    for section_name, section in sections:
        for tool_id, tool in section.items():
            for file_mapping in tool.files:
                local_path = file_mapping.resolved_source()
                
                if check_exists and not local_path.exists():
                    continue

                if is_sensitive(local_path):
                    continue
                
                is_dir = local_path.is_dir() if local_path.exists() else file_mapping.target.endswith("/")
                result.append((section_name, tool_id, file_mapping, local_path, is_dir))
    
    return result
