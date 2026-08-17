"""备份动作逻辑：备份、记录、应用与撤销变更。

业务决策与文件系统操作在此实现，注册表读写委托给 registry 模块。
"""
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.logger import get_logger
from .registry import (
    _find_existing_backup_in_dialog,
    _find_file_id_by_path,
    _generate_file_id,
    _get_file_backup_folder,
    _load_backup_registry,
    _save_backup_registry,
)

log = get_logger("Dolphin.backup_manager")


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

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")
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
        # 检查当前对话是否有未确认的备份。
        # 从末尾向前找：每次操作先 backup_file 追加记录、再 record_change，
        # 因此"最后一条未确认"即本次操作对应的记录，避免更新到更早的遗留记录。
        unconfirmed = None
        for backup in reversed(file_info.get("backup_files", [])):
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
