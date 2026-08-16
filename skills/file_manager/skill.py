from typing import Dict, Any
from pathlib import Path


def _safe_filename(file_path: str) -> str:
    try:
        return Path(file_path).name
    except Exception:
        return str(file_path) if file_path else "unknown"


skill_info = {
    "name": "file_manager",
    "description": "文件管理器技能，可以创建、修改和删除文件",
    "functions": {
        "set_work_directory": {
            "description": "设置工作目录（所有文件操作将限制在此目录内）。路径必须是当前工作目录的子目录，默认解析为相对路径。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "工作目录路径（建议使用相对路径格式，例如: 'subdir' 或 'subdir1/subdir2'）"}
                },
                "required": ["directory"]
            }
        },
        "create_file": {
            "description": "创建文件并写入内容。限制：最大文件大小10MB，最大行数1000行。此函数仅用于创建新文件。如果文件已存在，建议在修改已存在的文件时使用 modify_file 函数。创建文件时不要一次性写入过多内容，先创建基本框架，然后使用 modify_file 函数分多次进行修改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径（相对于工作目录），AI 可以决定文件名和后缀"},
                    "content": {"type": "string", "description": "文件内容，单次不要超过1000行"},
                    "encoding": {"type": "string", "description": "文件编码，默认为 'utf-8'"}
                },
                "required": ["file_path", "content"]
            }
        },
        "modify_file": {
            "description": "修改已存在的文件内容。当需要修改现有文件时，应优先使用此函数。提供要替换的原始字符串和新的字符串，将在文件中查找第一个完全匹配的 old_str 并替换为 new_str。此函数会自动创建备份文件，支持撤销恢复。提示：old_str 必须在文件中是唯一的，建议提供足够的上下文行以确保唯一匹配。限制：最大文件大小10MB。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径（相对于工作目录）"},
                    "old_str": {"type": "string", "description": "文件中要替换的原始字符串（包含完整上下文以确保唯一匹配）"},
                    "new_str": {"type": "string", "description": "用于替换的新字符串"},
                    "encoding": {"type": "string", "description": "文件编码，默认为 'utf-8'"}
                },
                "required": ["file_path", "old_str", "new_str"]
            }
        },
        "delete_file": {
            "description": "删除文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径（相对于工作目录）"}
                },
                "required": ["file_path"]
            }
        }
    }
}


def set_work_directory(context, directory: str) -> Dict[str, Any]:
    try:
        from modules.main_server.middleware.request_manager import get_persisted_work_directory, get_ai_work_directory
        base_work_dir = get_persisted_work_directory()
        base_path = Path(base_work_dir).resolve()

        ai_current_dir = get_ai_work_directory()
        if ai_current_dir:
            current_path = Path(ai_current_dir).resolve()
        else:
            current_path = base_path

        input_path = Path(directory)

        if input_path.is_absolute():
            resolved_path = input_path.resolve()
        else:
            resolved_path = (current_path / input_path).resolve()

        try:
            resolved_path.relative_to(base_path)
        except ValueError:
            resolved_path = base_path

        if not resolved_path.exists():
            return {"error": f"目录不存在: {resolved_path}", "user_output": {"label": "Work Place", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}
        if not resolved_path.is_dir():
            return {"error": f"路径不是目录: {resolved_path}", "user_output": {"label": "Work Place", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        relative_path = str(resolved_path.relative_to(base_path))
        if relative_path == ".":
            relative_path = ""
        temp_work_dir = str(resolved_path)

        return {
            "success": True,
            "work_directory": temp_work_dir,
            "relative_path": relative_path if relative_path else ".",
            "message": f"临时工作目录已切换为: {temp_work_dir}",
            "format_hint": "建议使用相对路径格式，例如: 'subdir' 或 'subdir1/subdir2'，使用 '..' 返回上级目录",
            "warning": "注意：此设置为临时切换，下次对话开始时将恢复为默认工作目录",
            "user_output": {"label": "Work Place", "parts": [{"text": f"--{relative_path or '.'}"}]}
        }
    except Exception as e:
        return {"error": f"设置工作目录失败: {str(e)}", "user_output": {"label": "Work Place", "parts": [{"text": "--"}, {"text": "Error", "style": "red"}]}}


def create_file(context, file_path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    try:
        result = context.file_operation(
            "create_file",
            file_path=file_path,
            content=content,
            encoding=encoding,
        )
        if result.get("success"):
            full_path = result.get("file_path", file_path)
            parent = str(Path(full_path).parent)
            filename = Path(full_path).name
            line_count = result.get("line_count", 0)
            if parent and parent != ".":
                result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": f"--{parent}", "style": "gray"}, {"text": f"+{line_count}", "style": "green"}, {"text": "-0", "style": "red"}]}
            else:
                result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": f"+{line_count}", "style": "green"}, {"text": "-0", "style": "red"}]}
        else:
            filename = _safe_filename(file_path)
            result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": "Error", "style": "red"}]}
        return result
    except Exception as e:
        filename = _safe_filename(file_path)
        return {"error": f"创建文件失败: {str(e)}", "user_output": {"label": "File Change", "parts": [{"text": filename}, {"text": "Error", "style": "red"}]}}


def modify_file(context, file_path: str, old_str: str, new_str: str, encoding: str = "utf-8") -> Dict[str, Any]:
    try:
        result = context.file_operation(
            "modify_file",
            file_path=file_path,
            old_str=old_str,
            new_str=new_str,
            encoding=encoding,
        )
        if result.get("success"):
            full_path = result.get("file_path", file_path)
            parent = str(Path(full_path).parent)
            filename = Path(full_path).name
            old_lines = result.get("old_lines", 0)
            new_lines = result.get("new_lines", 0)
            if parent and parent != ".":
                result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": f"--{parent}", "style": "gray"}, {"text": f"+{new_lines}", "style": "green"}, {"text": f"-{old_lines}", "style": "red"}]}
            else:
                result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": f"+{new_lines}", "style": "green"}, {"text": f"-{old_lines}", "style": "red"}]}
        else:
            filename = _safe_filename(file_path)
            result["user_output"] = {"label": "File Change", "parts": [{"text": filename}, {"text": "Error", "style": "red"}]}
        return result
    except Exception as e:
        filename = _safe_filename(file_path)
        return {"error": f"修改文件失败: {str(e)}", "user_output": {"label": "File Change", "parts": [{"text": filename}, {"text": "Error", "style": "red"}]}}


def delete_file(context, file_path: str, confirmed: bool = False) -> Dict[str, Any]:
    if not confirmed:
        filename = _safe_filename(file_path)
        return {
            "requires_confirmation": True,
            "message": f"确认删除文件: {file_path}",
            "action": "delete_file",
            "file_path": file_path,
            "work_directory": context.work_directory,
            "user_output": {"label": "File Change", "parts": [{"text": f"--{filename}"}, {"text": "?", "style": "yellow"}]}
        }

    try:
        result = context.file_operation(
            "delete_file",
            file_path=file_path,
        )
        if result.get("success"):
            full_path = result.get("file_path", file_path)
            filename = Path(full_path).name
            result["user_output"] = {"label": "File Change", "parts": [{"text": f"--{filename}"}, {"text": "Deleted", "style": "red"}]}
        else:
            filename = _safe_filename(file_path)
            result["user_output"] = {"label": "File Change", "parts": [{"text": f"--{filename}"}, {"text": "Error", "style": "red"}]}
        return result
    except Exception as e:
        filename = _safe_filename(file_path)
        return {"error": f"删除文件失败: {str(e)}", "user_output": {"label": "File Change", "parts": [{"text": f"--{filename}"}, {"text": "Error", "style": "red"}]}}
