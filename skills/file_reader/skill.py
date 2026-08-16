from typing import Dict, Any, List
from pathlib import Path


skill_info = {
    "name": "file_reader",
    "description": "文件阅读器技能，可以搜索文件、列出目录结构和阅读文件内容",
    "functions": {
        "get_work_directory": {
            "description": "获取当前工作目录",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "search_files": {
            "description": "在指定目录下搜索文件（支持文件名和内容搜索）。限制：最多返回500个结果，内容搜索最多检查100个文件，跳过大于10MB的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索模式（文件名或内容关键词）"},
                    "directory": {"type": "string", "description": "搜索目录（相对于工作目录），默认为当前目录"},
                    "search_in_content": {"type": "boolean", "description": "是否在文件内容中搜索，默认为 false"},
                    "file_extension": {"type": "string", "description": "文件扩展名过滤（如 '.py', '.txt'），默认为所有文件"}
                },
                "required": ["pattern"]
            }
        },
        "list_directory": {
            "description": "列出目录结构（树形结构显示）。限制：最多显示1000个文件，最大递归深度10。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "目录路径（相对于工作目录），默认为当前目录"},
                    "max_depth": {"type": "integer", "description": "最大递归深度，默认为 10"},
                    "show_hidden": {"type": "boolean", "description": "是否显示隐藏文件，默认为 false"}
                },
                "required": []
            }
        },
        "read_file": {
            "description": "读取文件内容。每次最多读取1000行，支持分页读取。限制：最大文件大小10MB。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径（相对于工作目录）"},
                    "offset": {"type": "integer", "description": "起始行号（从0开始），默认为0"},
                    "limit": {"type": "integer", "description": "读取行数，默认为1000，最大为1000"},
                    "encoding": {"type": "string", "description": "文件编码，默认为 'utf-8'"}
                },
                "required": ["file_path"]
            }
        }
    }
}


def get_work_directory(context) -> Dict[str, Any]:
    wd = context.work_directory
    return {
        "success": True,
        "work_directory": wd,
        "user_output": {"label": "Read", "parts": [{"text": wd}]}
    }


def search_files(context, pattern: str, directory: str = ".", search_in_content: bool = False, file_extension: str = None) -> Dict[str, Any]:
    wd = context.work_directory
    try:
        path_check = context.is_path_allowed(directory)
        if not path_check["allowed"]:
            return {"error": path_check["message"], "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的路径后再进行操作", "user_output": {"label": "Search", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        search_path = Path(wd) / directory

        if not search_path.exists():
            return {"error": f"目录不存在: {directory}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的路径后再进行操作", "user_output": {"label": "Search", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        if not search_path.is_dir():
            return {"error": f"路径不是目录: {directory}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的路径后再进行操作", "user_output": {"label": "Search", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        results = []
        files_searched = 0

        if search_in_content:
            for file_path in search_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_extension and file_path.suffix != file_extension:
                    continue
                if files_searched >= context.constants.MAX_FILES_TO_SEARCH_IN_CONTENT:
                    break
                files_searched += 1
                try:
                    file_size = file_path.stat().st_size
                    if file_size > context.constants.MAX_FILE_SIZE:
                        continue
                    if not context.is_path_allowed(str(file_path)).get("allowed"):
                        continue
                    matched_lines = []
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for line_num, line in enumerate(f, 1):
                            if len(matched_lines) >= context.constants.MAX_MATCHES_PER_FILE:
                                break
                            if pattern.lower() in line.lower():
                                matched_lines.append({
                                    "line": line_num,
                                    "content": line.rstrip('\n\r')
                                })
                    if matched_lines:
                        relative_path = file_path.relative_to(Path(wd))
                        results.append({
                            "name": file_path.name,
                            "path": str(relative_path),
                            "size": file_size,
                            "matches": matched_lines,
                            "match_count": len(matched_lines)
                        })
                        if len(results) >= context.constants.MAX_SEARCH_RESULTS:
                            break
                except Exception as e:
                    context.log_warning(f"搜索文件内容失败: {file_path}: {e}")
        else:
            for file_path in search_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_extension and file_path.suffix != file_extension:
                    continue
                if len(results) >= context.constants.MAX_SEARCH_RESULTS:
                    break
                if pattern.lower() in file_path.name.lower():
                    if not context.is_path_allowed(str(file_path)).get("allowed"):
                        continue
                    relative_path = file_path.relative_to(Path(wd))
                    results.append({
                        "name": file_path.name,
                        "path": str(relative_path),
                        "size": file_path.stat().st_size
                    })

        truncated = False
        if search_in_content:
            truncated = files_searched >= context.constants.MAX_FILES_TO_SEARCH_IN_CONTENT or len(results) >= context.constants.MAX_SEARCH_RESULTS
        else:
            truncated = len(results) >= context.constants.MAX_SEARCH_RESULTS

        return {
            "success": True,
            "directory": directory,
            "pattern": pattern,
            "search_in_content": search_in_content,
            "count": len(results),
            "files": results,
            "truncated": truncated,
            "max_results": context.constants.MAX_SEARCH_RESULTS,
            "files_searched": files_searched if search_in_content else None,
            "user_output": {"label": "Search", "parts": [{"text": f"--{pattern}"}]}
        }

    except Exception as e:
        return {"error": f"搜索文件失败: {str(e)}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件信息后再进行操作", "user_output": {"label": "Search", "parts": [{"text": "--"}, {"text": "Error", "style": "red"}]}}


def list_directory(context, directory: str = ".", max_depth: int = 10, show_hidden: bool = False) -> Dict[str, Any]:
    wd = context.work_directory
    try:
        path_check = context.is_path_allowed(directory)
        if not path_check["allowed"]:
            return {"error": path_check["message"], "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        list_path = Path(wd) / directory

        if not list_path.exists():
            return {"error": f"目录不存在: {directory}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的目录路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        if not list_path.is_dir():
            return {"error": f"路径不是目录: {directory}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的目录路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{directory}"}, {"text": "Error", "style": "red"}]}}

        file_count = 0

        def build_tree(path: Path, prefix: str = "", depth: int = 0) -> List[str]:
            nonlocal file_count
            if depth > max_depth:
                return []
            if file_count >= context.constants.MAX_FILES_TO_READ:
                return [f"{prefix}└── ... (已达到最大文件数量限制 {context.constants.MAX_FILES_TO_READ})"]
            lines = []
            try:
                items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except Exception:
                return lines
            for i, item in enumerate(items):
                if not show_hidden and item.name.startswith('.'):
                    continue
                # 文件与目录均校验 .dpc 屏蔽规则，屏蔽的目录不再列出与递归
                if not context.is_path_allowed(str(item)).get("allowed"):
                    continue
                if file_count >= context.constants.MAX_FILES_TO_READ:
                    lines.append(f"{prefix}└── ... (已达到最大文件数量限制 {context.constants.MAX_FILES_TO_READ})")
                    break
                is_last = i == len(items) - 1
                current_prefix = "└── " if is_last else "├── "
                lines.append(f"{prefix}{current_prefix}{item.name}")
                file_count += 1
                if item.is_dir():
                    extension = "    " if is_last else "│   "
                    lines.extend(build_tree(item, prefix + extension, depth + 1))
            return lines

        tree_lines = build_tree(list_path)

        target_dir = str(list_path.relative_to(Path(wd))) if str(list_path.relative_to(Path(wd))) != "." else "all"

        return {
            "success": True,
            "directory": directory,
            "tree": "\n".join(tree_lines),
            "line_count": len(tree_lines),
            "file_count": file_count,
            "truncated": file_count >= context.constants.MAX_FILES_TO_READ,
            "user_output": {"label": "Read", "parts": [{"text": f"--{target_dir}\\"}]}
        }

    except Exception as e:
        return {"error": f"列出目录失败: {str(e)}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件信息后再进行操作", "user_output": {"label": "Read", "parts": [{"text": "--"}, {"text": "Error", "style": "red"}]}}


def read_file(context, file_path: str, offset: int = 0, limit: int = 1000, encoding: str = "utf-8") -> Dict[str, Any]:
    wd = context.work_directory
    try:
        path_check = context.is_path_allowed(file_path)
        if not path_check["allowed"]:
            return {"error": path_check["message"], "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}, {"text": "Error", "style": "red"}]}}

        path = Path(wd) / file_path

        if not path.exists():
            return {"error": f"文件不存在: {file_path}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}, {"text": "Error", "style": "red"}]}}

        if not path.is_file():
            return {"error": f"路径不是文件: {file_path}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件路径后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}, {"text": "Error", "style": "red"}]}}

        file_size = path.stat().st_size

        if file_size > context.constants.MAX_FILE_SIZE:
            return {
                "error": f"文件过大: {file_path} (大小: {file_size} 字节，最大允许: {context.constants.MAX_FILE_SIZE} 字节)",
                "file_size": file_size,
                "max_size": context.constants.MAX_FILE_SIZE,
                "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件信息后再进行操作",
                "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}, {"text": "Error", "style": "red"}]}
            }

        with open(path, 'r', encoding=encoding, errors='ignore') as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)

        if offset >= total_lines:
            return {
                "success": True,
                "file_path": str(path.relative_to(Path(wd))),
                "encoding": encoding,
                "content": "",
                "line_count": 0,
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "has_more": False,
                "size": file_size,
                "message": f"已到达文件末尾，文件共 {total_lines} 行",
                "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}]}
            }

        end_line = min(offset + limit, total_lines)
        selected_lines = all_lines[offset:end_line]

        lines_out = [line.rstrip('\n\r') if line else '' for line in selected_lines]
        content = "\n".join(lines_out)

        return {
            "success": True,
            "file_path": str(path.relative_to(Path(wd))),
            "encoding": encoding,
            "content": content,
            "line_count": len(selected_lines),
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "start_line": offset + 1,
            "end_line": end_line,
            "has_more": end_line < total_lines,
            "size": file_size,
            "message": f"读取第 {offset + 1}-{end_line} 行，共 {total_lines} 行",
            "user_output": {"label": "Read", "parts": [{"text": f"--{str(path.relative_to(Path(wd)))}"}, {"text": f"{offset + 1}-{end_line}", "style": "gray"}]}
        }

    except Exception as e:
        return {"error": f"读取文件失败: {str(e)}", "suggestion": "建议使用 read_file 函数重新阅读文件，获取正确的文件信息后再进行操作", "user_output": {"label": "Read", "parts": [{"text": f"--{file_path}"}, {"text": "Error", "style": "red"}]}}
