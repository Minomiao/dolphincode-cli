"""备份注册表数据层：路径计算与 backup_registry.json 读写。

由 backup_manager 门面经 backup_actions 调用，不含任何业务动作。
"""
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from modules.logger import get_logger
from modules import bootstrap as app_paths

log = get_logger("Dolphin.backup_manager")

# ===== 会话文件夹内备份 =====
CONVERSATIONS_DIR = app_paths.CONVERSATIONS_DIR


def _get_conv_folder(dir_id: str, conv_id: str) -> Path:
    """获取会话文件夹路径"""
    return Path(CONVERSATIONS_DIR) / dir_id / conv_id


def _get_backup_registry_path(dir_id: str, conv_id: str) -> Path:
    """获取备份注册表路径"""
    return _get_conv_folder(dir_id, conv_id) / "backup_registry.json"


def _get_backups_folder(dir_id: str, conv_id: str) -> Path:
    """获取备份文件夹根路径（文件按 file_id 统一管理，不按 dialog_id 分层）"""
    return _get_conv_folder(dir_id, conv_id) / "backups"


def _get_file_backup_folder(dir_id: str, conv_id: str, file_id: str) -> Path:
    """获取特定文件的备份文件夹路径"""
    return _get_backups_folder(dir_id, conv_id) / file_id


def _load_backup_registry(dir_id: str, conv_id: str) -> Dict[str, Any]:
    """加载备份注册表"""
    registry_path = _get_backup_registry_path(dir_id, conv_id)
    if registry_path.exists():
        try:
            with open(registry_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"加载备份注册表失败: {e}")

    # 返回默认结构
    return {
        "conv_id": conv_id,
        "dialog_id": conv_id,  # dialog_id = conv_id
        "backups": {}  # {file_id: {file_path, work_dir, backup_files: []}}
    }


def _save_backup_registry(dir_id: str, conv_id: str, registry: Dict[str, Any]) -> None:
    """保存备份注册表（先写临时文件再原子替换，避免写盘中断损坏 JSON）。"""
    registry_path = _get_backup_registry_path(dir_id, conv_id)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = registry_path.with_name(registry_path.name + ".tmp")
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, registry_path)
    except Exception:
        # 清理临时文件，避免残留
        try:
            tmp_path.unlink()
        except Exception:
            pass
        raise
    log.debug(f"保存备份注册表: {registry_path}")


def _generate_file_id() -> str:
    """生成文件备份ID"""
    return str(uuid.uuid4())[:8]  # 短UUID，例如 "abc12345"


def _find_file_id_by_path(registry: Dict[str, Any], file_path: str) -> Optional[str]:
    """根据文件路径查找 file_id"""
    for file_id, info in registry.get("backups", {}).items():
        if info.get("file_path") == file_path:
            return file_id
    return None


def _find_existing_backup_in_dialog(registry: Dict[str, Any], file_path: str, dialog_id: str) -> Optional[str]:
    """检查当前对话是否已备份过该文件"""
    file_id = _find_file_id_by_path(registry, file_path)
    if not file_id:
        return None

    # 检查是否有当前 dialog_id 的备份
    file_info = registry["backups"][file_id]
    for backup in file_info.get("backup_files", []):
        if backup.get("dialog_id") == dialog_id and not backup.get("confirmed", False):
            return backup.get("backup_file")

    return None
