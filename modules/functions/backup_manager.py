import os
import shutil
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import json
import uuid
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

def backup_file(
    file_path: str,
    work_dir: str,
    dir_id: str,
    conv_id: str,
    action: str = "modify"
) -> Optional[str]:
    """
    在会话文件夹内创建备份。

    文件按 file_id 统一管理，不按 dialog_id 分层。
    dialog_id 记录在 backup_registry.json 中。

    Args:
        file_path: 文件相对路径
        work_dir: 工作目录
        dir_id: 会话目录ID
        conv_id: 会话ID（也是 dialog_id）
        action: 操作类型（create, modify, delete）

    Returns:
        备份文件路径（成功）或 None（失败或跳过）
    """
    start = time.perf_counter()
    try:
        full_path = Path(work_dir) / file_path
        
        # 对于创建操作，不需要备份
        if action == "create" or not full_path.exists():
            log.debug(f"跳过备份: {file_path} (action={action}, exists={full_path.exists()})")
            return None
        
        # 加载备份注册表
        registry = _load_backup_registry(dir_id, conv_id)
        dialog_id = conv_id  # dialog_id = conv_id
        
        # 检查当前对话是否已备份过该文件
        existing_backup = _find_existing_backup_in_dialog(registry, file_path, dialog_id)
        if existing_backup:
            log.debug(f"当前对话已存在备份: {file_path}")
            return existing_backup
        
        # 查找或创建 file_id（同一文件统一管理）
        file_id = _find_file_id_by_path(registry, file_path)
        if not file_id:
            file_id = _generate_file_id()
            registry["backups"][file_id] = {
                "file_path": file_path,
                "work_dir": work_dir,
                "backup_files": []
            }
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{timestamp}.bak"
        
        # 创建备份文件夹：backups/{file_id}/（统一管理，不按 dialog_id 分层）
        backup_folder = _get_file_backup_folder(dir_id, conv_id, file_id)
        backup_folder.mkdir(parents=True, exist_ok=True)
        backup_path = backup_folder / backup_filename
        
        log.info(f"备份文件: {file_path} -> {backup_path}")
        
        # 复制文件到备份位置
        shutil.copy2(full_path, backup_path)
        
        # 记录到备份注册表
        backup_record = {
            "backup_file": str(backup_path),
            "timestamp": datetime.now().isoformat(),
            "dialog_id": dialog_id,
            "action": action,
            "confirmed": False,
            "applied": False
        }
        registry["backups"][file_id]["backup_files"].append(backup_record)
        
        # 保存备份注册表
        _save_backup_registry(dir_id, conv_id, registry)
        
        elapsed = time.perf_counter() - start
        log.debug(f"备份完成: {file_path}, action={action}, file_id={file_id}, 耗时={elapsed:.3f}s")
        return str(backup_path)
    except Exception as e:
        elapsed = time.perf_counter() - start
        log.error(f"备份文件失败: {file_path}, 耗时={elapsed:.3f}s, 错误: {e}")
        return None

def record_change(
    action: str,
    file_path: str,
    work_dir: str,
    dir_id: str,
    conv_id: str
) -> Dict[str, Any]:
    """记录文件更改（基于 backup_registry.json）"""
    log.debug(f"记录更改: {file_path}, action={action}")
    
    registry = _load_backup_registry(dir_id, conv_id)
    dialog_id = conv_id
    
    # 查找文件的 file_id
    file_id = _find_file_id_by_path(registry, file_path)
    
    if file_id:
        file_info = registry["backups"][file_id]
        # 检查当前对话是否有未确认的备份
        unconfirmed = None
        for backup in file_info.get("backup_files", []):
            if backup.get("dialog_id") == dialog_id and not backup.get("confirmed", False):
                unconfirmed = backup
                break
        
        if unconfirmed:
            # 更新现有记录
            unconfirmed["action"] = action
            unconfirmed["timestamp"] = datetime.now().isoformat()
            log.debug(f"更新未确认的备份记录: {file_path}")
        else:
            # 创建新记录（无对应备份文件，例如 create 操作）
            backup_record = {
                "backup_file": None,
                "timestamp": datetime.now().isoformat(),
                "dialog_id": dialog_id,
                "action": action,
                "applied": False,
                "confirmed": False
            }
            file_info["backup_files"].append(backup_record)
            log.debug(f"创建新的备份记录: {file_path}")
        
        if work_dir:
            file_info["work_dir"] = work_dir
    else:
        # 文件不在注册表中，创建新记录
        file_id = _generate_file_id()
        backup_record = {
            "backup_file": None,
            "timestamp": datetime.now().isoformat(),
            "dialog_id": dialog_id,
            "action": action,
            "applied": False,
            "confirmed": False
        }
        registry["backups"][file_id] = {
            "file_path": file_path,
            "work_dir": work_dir,
            "backup_files": [backup_record]
        }
        log.debug(f"创建新的文件记录: {file_path}, file_id={file_id}")
    
    _save_backup_registry(dir_id, conv_id, registry)
    return registry["backups"][file_id]["backup_files"][-1]

def get_pending_changes_count(dir_id: str, conv_id: str) -> int:
    """获取待确认的更改数量"""
    registry = _load_backup_registry(dir_id, conv_id)
    count = 0
    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False):
                count += 1
    return count

def get_pending_changes_list(dir_id: str, conv_id: str) -> List[Dict[str, Any]]:
    """获取待确认的更改列表"""
    registry = _load_backup_registry(dir_id, conv_id)
    pending_changes = []
    
    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False):
                pending_changes.append({
                    "file_path": file_info.get("file_path", ""),
                    "work_dir": file_info.get("work_dir", ""),
                    "file_id": file_id,
                    **backup
                })
    
    return pending_changes

def apply_all_changes(dir_id: str, conv_id: str) -> Dict[str, Any]:
    """应用所有待确认的更改"""
    start = time.perf_counter()
    log.info(f"开始应用所有待确认的更改: conv={conv_id}")
    registry = _load_backup_registry(dir_id, conv_id)
    results = []
    applied_count = 0
    
    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False):
                backup["confirmed"] = True
                backup["applied"] = True
                results.append({
                    "file": file_info.get("file_path", ""),
                    "action": backup.get("action", ""),
                    "status": "applied"
                })
                applied_count += 1
                log.info(f"应用更改: {file_info.get('file_path', '')}, action={backup.get('action', '')}")
    
    _save_backup_registry(dir_id, conv_id, registry)
    
    elapsed = time.perf_counter() - start
    log.info(f"应用更改完成: {applied_count} 个, 耗时={elapsed:.3f}s")
    return {
        "success": True,
        "applied_count": applied_count,
        "changes": results,
        "message": f"已应用 {applied_count} 个更改"
    }

def revert_all_changes(dir_id: str, conv_id: str) -> Dict[str, Any]:
    """撤销所有待确认的更改。

    撤销时不保留备份文件，直接删除。
    """
    start = time.perf_counter()
    log.info(f"开始撤销所有待确认的更改: conv={conv_id}")
    registry = _load_backup_registry(dir_id, conv_id)
    results = []
    reverted_count = 0
    
    for file_id, file_info in list(registry.get("backups", {}).items()):
        file_path = file_info.get("file_path", "")
        work_dir = file_info.get("work_dir", "workplace")
        full_path = Path(work_dir) / file_path if file_path else None
        
        # 从后往前处理备份
        new_backup_files = []
        for backup in file_info.get("backup_files", []):
            if backup.get("confirmed", False):
                # 保留已确认的
                new_backup_files.append(backup)
                continue
            
            action = backup.get("action", "")
            backup_file_path = backup.get("backup_file")
            
            try:
                if action == "create":
                    # 创建操作：删除文件
                    if full_path and full_path.exists():
                        full_path.unlink()
                        results.append({
                            "file": file_path,
                            "action": "create",
                            "status": "reverted (deleted)"
                        })
                        reverted_count += 1
                        log.info(f"撤销创建: 删除文件 {file_path}")
                    else:
                        results.append({
                            "file": file_path,
                            "action": "create",
                            "status": "file not found"
                        })
                elif action in ["modify", "delete"]:
                    # 修改或删除操作：从备份恢复
                    if backup_file_path:
                        backup_path_obj = Path(backup_file_path)
                        if backup_path_obj.exists() and full_path:
                            shutil.copy2(backup_path_obj, full_path)
                            # 撤销时删除备份文件（不保留）
                            backup_path_obj.unlink()
                            results.append({
                                "file": file_path,
                                "action": action,
                                "status": "reverted (restored from backup)"
                            })
                            reverted_count += 1
                            log.info(f"撤销{action}: 恢复文件 {file_path}")
                        else:
                            results.append({
                                "file": file_path,
                                "action": action,
                                "status": "backup not found"
                            })
                            log.warning(f"撤销{action}失败: 备份不存在 {file_path}")
            except Exception as e:
                results.append({
                    "file": file_path,
                    "action": action,
                    "status": "failed",
                    "error": str(e)
                })
                log.error(f"撤销更改失败: {file_path}, action={action}, 错误: {e}")
                # 失败的记录保留
                new_backup_files.append(backup)
        
        # 更新备份列表（只保留已确认和失败的）
        file_info["backup_files"] = new_backup_files
    
    _save_backup_registry(dir_id, conv_id, registry)
    
    elapsed = time.perf_counter() - start
    log.info(f"撤销更改完成: {reverted_count} 个, 耗时={elapsed:.3f}s")
    return {
        "success": True,
        "reverted_count": reverted_count,
        "changes": results,
        "message": f"已撤销 {reverted_count} 个更改"
    }

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