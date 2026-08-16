import os
import json
import uuid
import ctypes
from datetime import datetime
from modules.logger import get_logger
from modules.bootstrap import constants

log = get_logger("Dolphin.dpc_manager")

DPC_FILENAME = constants.DPC_FILENAME
FILE_ATTRIBUTE_HIDDEN = constants.FILE_ATTRIBUTE_HIDDEN


def _read_raw(work_dir):
    """读取 .dpc 文件的原始数据。

    Args:
        work_dir: 工作目录

    Returns:
        解析后的字典数据；文件不存在或损坏时返回 None
    """
    dpc_path = os.path.join(work_dir, DPC_FILENAME)
    if not os.path.exists(dpc_path):
        return None
    try:
        with open(dpc_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        log.warning(f".dpc 文件损坏: {dpc_path}")
        return None


def _set_hidden(path):
    """为指定路径设置 Windows 隐藏属性。"""
    if os.name == 'nt':
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        ctypes.windll.kernel32.SetFileAttributesW(path, attrs | FILE_ATTRIBUTE_HIDDEN)


def _remove_hidden(path):
    if os.name == 'nt' and os.path.exists(path):
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        if attrs & FILE_ATTRIBUTE_HIDDEN:
            ctypes.windll.kernel32.SetFileAttributesW(path, attrs & ~FILE_ATTRIBUTE_HIDDEN)


def _write_raw(work_dir, data):
    """将数据写入 .dpc 文件并设置为隐藏。"""
    dpc_path = os.path.join(work_dir, DPC_FILENAME)
    _remove_hidden(dpc_path)
    with open(dpc_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _set_hidden(dpc_path)


def _migrate_old_format(data):
    if "dir_id" in data and "conversations" in data and isinstance(data["conversations"], list):
        if data["conversations"] and isinstance(data["conversations"][0], dict):
            if "restricted" not in data:
                data["restricted"] = [".dpc"]
            return data
    new = {
        "dir_id": data.get("dir_id", str(uuid.uuid4())),
        "conversations": [],
        "current": None,
        "updated_at": data.get("updated_at", datetime.now().isoformat()),
        "restricted": data.get("restricted", [".dpc"])
    }
    old_convs = data.get("conversations", [])
    old_current = data.get("current") or data.get("conversation")
    old_conversation = data.get("conversation")
    if old_conversation and old_conversation not in old_convs:
        old_convs.append(old_conversation)
    for name in old_convs:
        conv_id = str(uuid.uuid4())
        new["conversations"].append({"id": conv_id, "name": name})
        if name == old_current or name == old_conversation:
            new["current"] = conv_id
    if not new["current"] and new["conversations"]:
        new["current"] = new["conversations"][0]["id"]
    log.info(f"迁移旧 .dpc 格式: {len(new['conversations'])} 个对话")
    return new


def get_dir_id(work_dir):
    """获取工作目录的 dir_id。"""
    data = _read_raw(work_dir)
    if data is None:
        return None
    data = _migrate_old_format(data)
    return data.get("dir_id")


def ensure_dir_id(work_dir):
    data = _read_raw(work_dir)
    if data is not None:
        data = _migrate_old_format(data)
        needs_write = False
        if "dir_id" not in data:
            data["dir_id"] = str(uuid.uuid4())
            needs_write = True
        if "restricted" not in data:
            data["restricted"] = [".dpc"]
            needs_write = True
        if needs_write:
            _write_raw(work_dir, data)
        return data["dir_id"]
    dir_id = str(uuid.uuid4())
    data = {
        "dir_id": dir_id,
        "conversations": [],
        "current": None,
        "updated_at": datetime.now().isoformat(),
        "restricted": [".dpc"]
    }
    _write_raw(work_dir, data)
    log.info(f".dpc 初始化: dir_id={dir_id}")
    return dir_id


def get_conversations(work_dir):
    """获取工作目录下的对话列表。"""
    data = _read_raw(work_dir)
    if data is None:
        return []
    data = _migrate_old_format(data)
    return data.get("conversations", [])


def get_current(work_dir):
    """获取当前对话的 (id, name)；无对话时返回 (None, None)。"""
    data = _read_raw(work_dir)
    if data is None:
        return None, None
    data = _migrate_old_format(data)
    current_id = data.get("current")
    if not current_id:
        return None, None
    for c in data.get("conversations", []):
        if c["id"] == current_id:
            return current_id, c["name"]
    return current_id, None


def get_name_by_id(work_dir, conv_id):
    """根据对话 id 获取对话名称。"""
    data = _read_raw(work_dir)
    if data is None:
        return None
    data = _migrate_old_format(data)
    for c in data.get("conversations", []):
        if c["id"] == conv_id:
            return c["name"]
    return None


def get_id_by_name(work_dir, name):
    """根据对话名称获取对话 id。"""
    data = _read_raw(work_dir)
    if data is None:
        return None
    data = _migrate_old_format(data)
    for c in data.get("conversations", []):
        if c["name"] == name:
            return c["id"]
    return None


def add_conversation(work_dir, name):
    """新增对话，若同名对话已存在则切换到该对话，返回对话 id。"""
    data = _read_raw(work_dir) or {}
    data = _migrate_old_format(data)
    for c in data["conversations"]:
        if c["name"] == name:
            data["current"] = c["id"]
            data["updated_at"] = datetime.now().isoformat()
            _write_raw(work_dir, data)
            log.info(f".dpc: 切换到已有对话 '{name}' -> {c['id']}")
            return c["id"]
    conv_id = str(uuid.uuid4())
    data["conversations"].append({"id": conv_id, "name": name})
    data["current"] = conv_id
    data["updated_at"] = datetime.now().isoformat()
    _write_raw(work_dir, data)
    log.info(f".dpc: 新增对话 '{name}' -> {conv_id}")
    return conv_id


def set_current_by_id(work_dir, conv_id):
    """将指定对话 id 设为当前对话。"""
    data = _read_raw(work_dir)
    if data is None:
        return
    data = _migrate_old_format(data)
    data["current"] = conv_id
    data["updated_at"] = datetime.now().isoformat()
    _write_raw(work_dir, data)
    log.info(f".dpc: current -> {conv_id}")


def get_restricted_paths(work_dir):
    """获取 .dpc 屏蔽规则列表。"""
    data = _read_raw(work_dir)
    if data is None:
        return [".dpc"]
    data = _migrate_old_format(data)
    return data.get("restricted", [".dpc"])


def is_path_allowed(work_dir, relative_path):
    """判断相对路径是否被 .dpc 屏蔽规则允许访问。

    Args:
        work_dir: 工作目录
        relative_path: 待校验的相对路径

    Returns:
        (allowed, msg)：是否允许访问及被拒原因
    """
    import fnmatch
    restricted = get_restricted_paths(work_dir)
    normalized = relative_path.replace('\\', '/').lstrip('/')
    for pattern in restricted:
        if pattern == "*":
            return False, f"目录 {work_dir} 禁止访问"
        if fnmatch.fnmatch(normalized, pattern):
            return False, f"文件 '{relative_path}' 被 .dpc 限制访问"
        if fnmatch.fnmatch(os.path.basename(normalized), pattern):
            return False, f"文件 '{relative_path}' 被 .dpc 限制访问"
    return True, None


def is_path_allowed_walkup(work_dir, absolute_path):
    """从文件所在目录向上逐级校验 .dpc 限制，直至工作目录。

    Args:
        work_dir: 工作目录
        absolute_path: 待校验文件的绝对路径

    Returns:
        (allowed, msg)：是否允许访问及原因
    """
    current = os.path.dirname(os.path.abspath(absolute_path))
    work_path = os.path.abspath(work_dir)
    while True:
        if os.path.exists(os.path.join(current, DPC_FILENAME)):
            rel = os.path.relpath(absolute_path, current)
            allowed, msg = is_path_allowed(current, rel)
            if not allowed:
                return False, msg
        parent = os.path.dirname(current)
        if parent == current or os.path.commonpath([parent, work_path]) != work_path:
            break
        current = parent
    return True, None


def filter_allowed_paths(work_dir, paths):
    """按 .dpc 屏蔽规则过滤路径列表。

    Returns:
        (allowed, blocked)：允许与被拒绝的路径列表
    """
    allowed = []
    blocked = []
    for p in paths:
        ok, _ = is_path_allowed(work_dir, p)
        if ok:
            allowed.append(p)
        else:
            blocked.append(p)
    return allowed, blocked


def ensure_restriction(work_dir, restricted_patterns):
    """确保指定屏蔽模式已加入 .dpc 限制规则。"""
    data = _read_raw(work_dir)
    if data is None:
        dpc_dir_id = str(uuid.uuid4())
        data = {
            "dir_id": dpc_dir_id,
            "conversations": [],
            "current": None,
            "updated_at": datetime.now().isoformat(),
            "restricted": [".dpc"]
        }
        _write_raw(work_dir, data)
        log.info(f".dpc 初始化(restriction): dir_id={dpc_dir_id}")
        data = _read_raw(work_dir)

    data = _migrate_old_format(data)
    existing = set(data.get("restricted", [".dpc"]))
    for p in restricted_patterns:
        existing.add(p)
    data["restricted"] = list(existing)
    data["updated_at"] = datetime.now().isoformat()
    _write_raw(work_dir, data)
    log.info(f".dpc restriction 已更新: {data['restricted']}")


def remove_restriction(work_dir, restricted_patterns):
    """从 .dpc 屏蔽规则中移除指定模式（".dpc" 始终保留）。"""
    data = _read_raw(work_dir)
    if data is None:
        return
    data = _migrate_old_format(data)
    existing = set(data.get("restricted", [".dpc"]))
    for p in restricted_patterns:
        existing.discard(p)
    existing.add(".dpc")
    data["restricted"] = list(existing)
    data["updated_at"] = datetime.now().isoformat()
    _write_raw(work_dir, data)
    log.info(f".dpc restriction 已移除: {data['restricted']}")
