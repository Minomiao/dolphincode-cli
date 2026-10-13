"""备份动作逻辑：备份、记录、应用与撤销变更。

业务决策与文件系统操作在此实现，注册表读写委托给 registry 模块。
"""
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from modules.bootstrap import constants
from modules.logger import get_logger
from .registry import (
    _find_file_id_by_path,
    _find_pending_record,
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

        # 命中当前对话未确认记录（含幽灵）：本轮撤销基线恒为轮初，
        # 同一文件至多一份快照，无需重复复制
        pending = _find_pending_record(registry, file_path, dialog_id)
        if pending is not None:
            log.debug(f"当前对话已存在未确认记录，复用快照: {file_path}")
            return pending.get("backup_file")

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


def _fold_action(prev_record: Dict[str, Any], new_action: str) -> Optional[str]:
    """净状态转移：将新操作折叠进当前未确认记录。

    净状态由 (撤销基线, 当前存在性) 决定，分两个互斥族：
    - 族 1（轮初不存在）：create 记录或已净零的幽灵。撤销动作恒为删除文件，
      后续 modify/create 复活为 create，delete 达到净零；
    - 族 2（轮初存在）：modify/delete 记录，撤销动作恒为恢复轮初快照，
      action 在 modify/delete 间切换，快照内容保持轮初不变。

    Args:
        prev_record: 当前未确认记录
        new_action: 新操作（create / modify / delete）

    Returns:
        折叠后的 action；None 表示净零（记录转为幽灵 canceled）。
    """
    if prev_record.get("canceled", False) or prev_record.get("action") == "create":
        # 族 1：基线=不存在
        return None if new_action == "delete" else "create"
    # 族 2：基线=存在+轮初快照
    return "modify" if new_action == "create" else new_action


def record_change(
    action: str,
    file_path: str,
    work_dir: str,
    dir_id: str,
    conv_id: str
) -> Dict[str, Any]:
    """记录文件更改（基于 backup_registry.json，按净状态折叠）"""
    log.debug(f"记录更改: {file_path}, action={action}")

    registry = _load_backup_registry(dir_id, conv_id)
    dialog_id = conv_id

    # 查找文件的 file_id
    file_id = _find_file_id_by_path(registry, file_path)

    if file_id:
        file_info = registry["backups"][file_id]
        # 查找当前对话的未确认记录（折叠机制保证至多一条，取最后兼容遗留）
        pending = None
        for backup in reversed(file_info.get("backup_files", [])):
            if backup.get("dialog_id") == dialog_id and not backup.get("confirmed", False):
                pending = backup
                break

        if pending is not None:
            folded = _fold_action(pending, action)
            pending["timestamp"] = datetime.now().isoformat()
            if folded is None:
                # 净零：本轮操作相互抵消，打幽灵标记（不参与 pending 展示与撤销）
                pending["canceled"] = True
                log.debug(f"操作净零，记录转为幽灵: {file_path}")
            else:
                pending["action"] = folded
                pending["canceled"] = False
                log.debug(f"折叠更新未确认记录: {file_path}, action={folded}")
        else:
            # 无未确认记录：新建（create 无快照；modify/delete 的快照
            # 已由 backup_file 先行创建并追加记录，正常不会走到此分支）
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
    """获取待确认的更改数量（幽灵记录不计入）"""
    registry = _load_backup_registry(dir_id, conv_id)
    count = 0
    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False) and not backup.get("canceled", False):
                count += 1
    return count


def get_pending_changes_list(dir_id: str, conv_id: str) -> List[Dict[str, Any]]:
    """获取待确认的更改列表（幽灵记录不计入）"""
    registry = _load_backup_registry(dir_id, conv_id)
    pending_changes = []

    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False) and not backup.get("canceled", False):
                pending_changes.append({
                    "file_path": file_info.get("file_path", ""),
                    "work_dir": file_info.get("work_dir", ""),
                    "file_id": file_id,
                    **backup
                })

    return pending_changes


def apply_all_changes(dir_id: str, conv_id: str) -> Dict[str, Any]:
    """应用所有待确认的更改（幽灵记录保持不变）"""
    start = time.perf_counter()
    log.info(f"开始应用所有待确认的更改: conv={conv_id}")
    registry = _load_backup_registry(dir_id, conv_id)
    results = []
    applied_count = 0

    for file_id, file_info in registry.get("backups", {}).items():
        for backup in file_info.get("backup_files", []):
            if not backup.get("confirmed", False) and not backup.get("canceled", False):
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
    """撤销所有待确认的更改（幽灵记录保持不变）。

    撤销时不保留备份文件，直接删除。
    恢复按逆序执行（先最新后最早），确保最终状态为最早快照；
    当前折叠机制保证每对话每文件至多一条未确认记录，逆序为防御性设计。
    """
    start = time.perf_counter()
    log.info(f"开始撤销所有待确认的更改: conv={conv_id}")
    registry = _load_backup_registry(dir_id, conv_id)
    results = []
    reverted_count = 0

    for file_id, file_info in list(registry.get("backups", {}).items()):
        file_path = file_info.get("file_path", "")
        work_dir = file_info.get("work_dir", constants.DEFAULT_WORK_DIR)
        full_path = Path(work_dir) / file_path if file_path else None

        original = file_info.get("backup_files", [])
        pending_reverts = [
            b for b in original
            if not b.get("confirmed", False) and not b.get("canceled", False)
        ]

        # 逆序执行恢复动作；成功的记录从列表移除，失败与已确认/幽灵的保留
        revert_ok_ids = set()
        for backup in reversed(pending_reverts):
            action = backup.get("action", "")
            backup_file_path = backup.get("backup_file")

            try:
                if action == "create":
                    # 创建操作：删除文件
                    if full_path and full_path.exists():
                        full_path.unlink()
                        revert_ok_ids.add(id(backup))
                        results.append({
                            "file": file_path,
                            "action": "create",
                            "status": "reverted (deleted)"
                        })
                        reverted_count += 1
                        log.info(f"撤销创建: 删除文件 {file_path}")
                    else:
                        # 文件已不在，撤销目标已达成，记录移除
                        revert_ok_ids.add(id(backup))
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
                            revert_ok_ids.add(id(backup))
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

        # 重建列表：保留已确认、幽灵与撤销失败的记录（维持原顺序）
        remaining = [
            b for b in original
            if b.get("confirmed", False) or b.get("canceled", False) or id(b) not in revert_ok_ids
        ]
        file_info["backup_files"] = remaining
        if not remaining:
            # 该文件无任何剩余记录，清理空条目
            del registry["backups"][file_id]

    _save_backup_registry(dir_id, conv_id, registry)

    elapsed = time.perf_counter() - start
    log.info(f"撤销更改完成: {reverted_count} 个, 耗时={elapsed:.3f}s")
    return {
        "success": True,
        "reverted_count": reverted_count,
        "changes": results,
        "message": f"已撤销 {reverted_count} 个更改"
    }
