"""备份管理器门面。

注册表读写见 registry.py，业务动作见 backup_actions.py；
本模块仅保留 BackupManager 会话上下文与单例工厂。
"""
from typing import Any, Dict, List, Optional

from modules.logger import get_logger
from .backup_actions import (
    apply_all_changes,
    backup_file,
    get_pending_changes_count,
    get_pending_changes_list,
    record_change,
    revert_all_changes,
)

log = get_logger("Dolphin.backup_manager")


# 单例模式
_backup_manager = None


class BackupManager:
    """备份管理器。

    通过 set_session() 设置当前会话上下文，
    后续所有操作自动使用该上下文。
    """

    def __init__(self):
        self._dir_id: Optional[str] = None
        self._conv_id: Optional[str] = None
        log.info("BackupManager 初始化完成")

    def set_session(self, dir_id: str, conv_id: str):
        """设置当前会话上下文"""
        self._dir_id = dir_id
        self._conv_id = conv_id
        log.info(f"BackupManager 会话已设置: dir={dir_id}, conv={conv_id}")

    def _check_session(self) -> bool:
        """检查会话上下文是否已设置"""
        if not self._dir_id or not self._conv_id:
            log.warning("BackupManager 会话上下文未设置，请先调用 set_session()")
            return False
        return True

    def backup_file(self, file_path: str, work_dir: str, action: str = "modify") -> Optional[str]:
        """备份文件"""
        if not self._check_session():
            return None
        return backup_file(file_path, work_dir, self._dir_id, self._conv_id, action)

    def record_change(self, action: str, file_path: str, work_dir: str = "") -> Dict[str, Any]:
        """记录文件更改"""
        if not self._check_session():
            return {}
        return record_change(action, file_path, work_dir, self._dir_id, self._conv_id)

    def get_pending_changes_count(self) -> int:
        """获取待确认的更改数量"""
        if not self._check_session():
            return 0
        return get_pending_changes_count(self._dir_id, self._conv_id)

    def get_pending_changes_list(self) -> List[Dict[str, Any]]:
        """获取待确认的更改列表"""
        if not self._check_session():
            return []
        return get_pending_changes_list(self._dir_id, self._conv_id)

    def apply_all_changes(self) -> Dict[str, Any]:
        """应用所有待确认的更改"""
        if not self._check_session():
            return {"success": False, "message": "会话上下文未设置"}
        return apply_all_changes(self._dir_id, self._conv_id)

    def revert_all_changes(self) -> Dict[str, Any]:
        """撤销所有待确认的更改"""
        if not self._check_session():
            return {"success": False, "message": "会话上下文未设置"}
        return revert_all_changes(self._dir_id, self._conv_id)


def get_backup_manager() -> BackupManager:
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager
