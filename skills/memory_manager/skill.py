"""项目记忆管理技能：实现同一项目内跨会话的记忆互通。

记忆存放于工作目录的 Dmemory 文件夹中：
- 每个记忆条目对应一个独立文档（{key}.md），直接存储正文；
- index.json 存储条目索引（标题、摘要、文档连接与时间信息）；
- 通过 .dpc 项目标识（dir_id）关联同一项目，供 AI 写入与查找记忆内容。
"""
import os
import json
import ctypes
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

MEMORY_DIR_NAME = "Dmemory"
INDEX_FILE_NAME = "index.json"
MAX_CONTENT_LENGTH = 20000
MAX_ENTRIES = 500
SUMMARY_LENGTH = 200
OUTPUT_LABEL = "Memory"


def _memory_dir(context) -> Path:
    """返回 Dmemory 文件夹路径。"""
    return Path(context.work_directory) / MEMORY_DIR_NAME


def _index_file(context) -> Path:
    """返回记忆索引文件路径。"""
    return _memory_dir(context) / INDEX_FILE_NAME


def _doc_path(context, doc_name: str) -> Path:
    """返回记忆文档路径，并校验其必须位于 Dmemory 目录内，防止路径穿越。

    Raises:
        ValueError: 文档路径越界（被 index.json 篡改时触发）
    """
    memory_root = _memory_dir(context).resolve()
    path = (memory_root / doc_name).resolve()
    if not path.is_relative_to(memory_root):
        raise ValueError(f"记忆文档路径越界: {doc_name}")
    return path


def _set_folder_hidden(context, folder: Path) -> None:
    """在 Windows 下为文件夹设置隐藏属性。"""
    if os.name == 'nt':
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(folder))
        ctypes.windll.kernel32.SetFileAttributesW(str(folder), attrs | context.constants.FILE_ATTRIBUTE_HIDDEN)


def _safe_doc_name(key: str) -> str:
    """将记忆 key 转换为安全的文档文件名（去除路径分隔符与非法字符）。"""
    name = re.sub(r'[^A-Za-z0-9._-]', '_', key).strip('.')
    if not name:
        name = "entry"
    return name[:80]


def _get_dir_id(context) -> str:
    """获取 .dpc 项目标识，记忆与其关联。"""
    try:
        from modules.chater import dpc_manager
        return dpc_manager.ensure_dir_id(context.work_directory)
    except Exception as e:
        context.log_warning(f"获取 .dpc 项目标识失败: {e}")
        return ""


def _ensure_restricted(context) -> None:
    """将 Dmemory 文件夹（含子路径）加入 .dpc 屏蔽规则，防止其他技能误改记忆库。

    "Dmemory" 只屏蔽文件夹本身，必须追加 "Dmemory/*" 才能屏蔽其内部文件。
    """
    patterns = [MEMORY_DIR_NAME, f"{MEMORY_DIR_NAME}/*"]
    try:
        existing = context.get_restricted_paths()
        missing = [p for p in patterns if p not in existing]
        if missing:
            context.add_restriction(missing)
    except Exception as e:
        context.log_warning(f"添加 .dpc 屏蔽规则失败: {e}")


def _save_folder(context) -> None:
    """确保 Dmemory 文件夹存在、隐藏且受 .dpc 保护。"""
    folder = _memory_dir(context)
    folder.mkdir(parents=True, exist_ok=True)
    _set_folder_hidden(context, folder)
    _ensure_restricted(context)


def _read_index(context) -> List[dict]:
    """读取记忆索引，文件不存在或损坏时返回空列表。"""
    path = _index_file(context)
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        entries = data.get("entries", [])
        return entries if isinstance(entries, list) else []
    except (json.JSONDecodeError, OSError) as e:
        context.log_warning(f"读取记忆索引失败: {e}")
        return []


def _write_index(context, entries: List[dict]) -> bool:
    """写入记忆索引，返回是否成功。"""
    _save_folder(context)
    try:
        data = {
            "dir_id": _get_dir_id(context),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "entries": entries,
        }
        with open(_index_file(context), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except (OSError, PermissionError) as e:
        context.log_warning(f"保存记忆索引失败: {e}")
        return False
    return True


def _write_doc(context, doc_name: str, content: str) -> bool:
    """写入记忆文档正文，返回是否成功。"""
    try:
        _save_folder(context)
        with open(_doc_path(context, doc_name), 'w', encoding='utf-8') as f:
            f.write(content)
    except (OSError, PermissionError, ValueError) as e:
        context.log_warning(f"保存记忆文档失败: {doc_name}: {e}")
        return False
    return True


def _read_doc(context, doc_name: str) -> str:
    """读取记忆文档正文，缺失或读取失败时返回空字符串。"""
    try:
        with open(_doc_path(context, doc_name), 'r', encoding='utf-8') as f:
            return f.read()
    except (OSError, PermissionError, ValueError) as e:
        context.log_warning(f"读取记忆文档失败: {doc_name}: {e}")
        return ""


def _delete_doc(context, doc_name: str) -> None:
    """删除记忆文档，失败仅记录日志。"""
    try:
        path = _doc_path(context, doc_name)
        if path.exists():
            path.unlink()
    except (OSError, ValueError) as e:
        context.log_warning(f"删除记忆文档失败: {doc_name}: {e}")


def _auto_summary(content: str) -> str:
    """根据正文自动生成摘要。"""
    content = content.strip()
    if len(content) <= SUMMARY_LENGTH:
        return content
    return content[:SUMMARY_LENGTH] + "..."


def _unique_doc_name(entries: List[dict], base_name: str) -> str:
    """生成不与现有条目冲突的文档文件名。"""
    used = {e.get("file") for e in entries}
    candidate = f"{base_name}.md"
    index = 2
    while candidate in used:
        candidate = f"{base_name}-{index}.md"
        index += 1
    return candidate


skill_info = {
    "name": "memory_manager",
    "description": "项目记忆管理技能，在同一项目中跨会话保存和检索记忆。适用于记录项目约定、决策、进度等需要跨会话保留的信息。",
    "functions": {
        "write_memory": {
            "description": "写入或更新一条项目记忆。若 key 已存在则覆盖更新。限制：单条正文不超过 20000 字符，总条目不超过 500 条。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆条目的唯一标识，使用下划线英文短语，如 'build_command'、'coding_style'"},
                    "title": {"type": "string", "description": "记忆标题，简短概括条目内容"},
                    "content": {"type": "string", "description": "记忆正文，完整记录需要保留的信息"},
                    "summary": {"type": "string", "description": "记忆摘要（可选），不填时自动截取正文前 200 字"}
                },
                "required": ["key", "title", "content"]
            }
        },
        "search_memory": {
            "description": "按关键词检索项目记忆，在 key、标题、摘要与正文中模糊匹配，返回匹配条目的摘要信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词"}
                },
                "required": ["query"]
            }
        },
        "get_memory": {
            "description": "按 key 获取一条记忆的完整正文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "记忆条目的唯一标识"}
                },
                "required": ["key"]
            }
        },
        "list_memory": {
            "description": "列出当前项目的所有记忆条目（key、标题、摘要），按更新时间倒序排列。",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        },
        "delete_memory": {
            "description": "删除一条项目记忆，索引与文档一并删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "要删除的记忆条目的唯一标识"}
                },
                "required": ["key"]
            }
        }
    }
}


def write_memory(context, key: str, title: str, content: str, summary: str = None) -> Dict[str, Any]:
    """写入或更新一条项目记忆，key 已存在时覆盖更新。"""
    key = (key or "").strip()
    title = (title or "").strip()
    content = content or ""
    if not key:
        return {"success": False, "error": "记忆 key 不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
    if not title:
        return {"success": False, "error": "记忆标题不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
    if not content.strip():
        return {"success": False, "error": "记忆正文不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
    if len(content) > MAX_CONTENT_LENGTH:
        return {"success": False, "error": f"记忆正文超过上限 {MAX_CONTENT_LENGTH} 字符", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}

    entries = _read_index(context)
    now = datetime.now().isoformat(timespec="seconds")
    doc_summary = (summary or "").strip() or _auto_summary(content)

    for entry in entries:
        if entry.get("key") == key:
            doc_name = entry.get("file") or f"{_safe_doc_name(key)}.md"
            if not _write_doc(context, doc_name, content):
                return {"success": False, "error": "保存记忆文档失败，请检查目录写入权限", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
            entry.update({"title": title, "summary": doc_summary, "updated_at": now})
            if not _write_index(context, entries):
                return {"success": False, "error": "保存记忆索引失败，请检查目录写入权限", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
            context.log_info(f"更新项目记忆: {key}")
            return {"success": True, "key": key, "message": "记忆已更新", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}]}}

    if len(entries) >= MAX_ENTRIES:
        return {"success": False, "error": f"记忆条目数已达上限 {MAX_ENTRIES}，请先删除无用条目", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}

    doc_name = _unique_doc_name(entries, _safe_doc_name(key))
    if not _write_doc(context, doc_name, content):
        return {"success": False, "error": "保存记忆文档失败，请检查目录写入权限", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
    entries.append({
        "key": key, "title": title, "summary": doc_summary, "file": doc_name,
        "created_at": now, "updated_at": now,
    })
    if not _write_index(context, entries):
        return {"success": False, "error": "保存记忆索引失败，请检查目录写入权限", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}, {"text": "Error", "style": "red"}]}}
    context.log_info(f"写入项目记忆: {key} -> {doc_name}")
    return {"success": True, "key": key, "message": "记忆已保存", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--write {key}"}]}}


def search_memory(context, query: str) -> Dict[str, Any]:
    """按关键词在 key、标题、摘要与正文中检索项目记忆。"""
    query = (query or "").strip().lower()
    if not query:
        return {"success": False, "error": "检索关键词不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "--search"}, {"text": "Error", "style": "red"}]}}

    matches = []
    for entry in _read_index(context):
        content = _read_doc(context, entry.get("file") or "")
        haystack = " ".join([
            entry.get("key") or "",
            entry.get("title") or "",
            entry.get("summary") or "",
            content,
        ]).lower()
        if query in haystack:
            matches.append({
                "key": entry.get("key"),
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "file": entry.get("file"),
                "updated_at": entry.get("updated_at"),
            })

    matches.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
    return {"success": True, "count": len(matches), "matches": matches, "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--search {query}"}]}}


def get_memory(context, key: str) -> Dict[str, Any]:
    """按 key 获取记忆条目的标题、摘要与完整正文。"""
    key = (key or "").strip()
    if not key:
        return {"success": False, "error": "记忆 key 不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--get {key}"}, {"text": "Error", "style": "red"}]}}
    for entry in _read_index(context):
        if entry.get("key") == key:
            content = _read_doc(context, entry.get("file") or "")
            return {
                "success": True,
                "key": key,
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "content": content,
                "file": entry.get("file"),
                "created_at": entry.get("created_at"),
                "updated_at": entry.get("updated_at"),
                "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--get {key}"}]},
            }
    return {"success": False, "error": f"未找到记忆条目: {key}", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--get {key}"}, {"text": "Error", "style": "red"}]}}


def list_memory(context) -> Dict[str, Any]:
    """列出全部记忆条目的标题与摘要信息。"""
    result = [
        {
            "key": e.get("key"),
            "title": e.get("title"),
            "summary": e.get("summary"),
            "file": e.get("file"),
            "updated_at": e.get("updated_at"),
        }
        for e in _read_index(context)
    ]
    result.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
    return {"success": True, "count": len(result), "entries": result, "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "--list"}]}}


def delete_memory(context, key: str) -> Dict[str, Any]:
    """删除一条项目记忆（索引与文档一并删除）。"""
    key = (key or "").strip()
    if not key:
        return {"success": False, "error": "记忆 key 不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--delete {key}"}, {"text": "Error", "style": "red"}]}}
    entries = _read_index(context)
    target = next((e for e in entries if e.get("key") == key), None)
    if target is None:
        return {"success": False, "error": f"未找到记忆条目: {key}", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--delete {key}"}, {"text": "Error", "style": "red"}]}}
    remaining = [e for e in entries if e.get("key") != key]
    if not _write_index(context, remaining):
        return {"success": False, "error": "保存记忆索引失败，请检查目录写入权限", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--delete {key}"}, {"text": "Error", "style": "red"}]}}
    _delete_doc(context, target.get("file") or "")
    context.log_info(f"删除项目记忆: {key}")
    return {"success": True, "key": key, "message": "记忆已删除", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"--delete {key}"}]}}
