"""Git 版本控制技能：初始化仓库、暂存、提交、查看状态与历史。

创建 .gitignore 时会自动从工作目录的 .dpc 屏蔽规则<restricted>中
获取内容并添加，确保被屏蔽的路径不会进入版本控制。
"""
import subprocess
from pathlib import Path
from typing import Dict, Any, List

OUTPUT_LABEL = "Git"
GIT_TIMEOUT = 60
DPC_SECTION_MARKER = "# === Dolphin .dpc 屏蔽规则"

# 通用忽略模板<仅在新文件首次创建时追加>
_COMMON_IGNORES = [
    "# === 通用忽略 ===",
    "__pycache__/",
    "*.py[cod]",
    "venv/",
    ".venv/",
    ".env",
    ".idea/",
    ".vscode/",
    ".DS_Store",
]


def _run_git(context, args: List[str]) -> Dict[str, Any]:
    """在工作目录中执行 git 命令并返回结果。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=context.work_directory,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except FileNotFoundError:
        return {"error": "未找到 git 命令，请确认已安装 Git"}
    except subprocess.TimeoutExpired:
        return {"error": f"git 命令执行超时<{GIT_TIMEOUT}s>"}
    except Exception as e:
        return {"error": f"git 命令执行失败: {e}"}


def _get_dpc_entries(context) -> List[str]:
    """从 .dpc 屏蔽规则获取 .gitignore 条目<自动剔除全禁模式 *>。"""
    try:
        restricted = context.get_restricted_paths()
    except Exception as e:
        context.log_warning(f"读取 .dpc 屏蔽规则失败: {e}")
        restricted = [".dpc"]
    entries = []
    for pattern in restricted:
        pattern = (pattern or "").strip()
        if pattern and pattern != "*":
            entries.append(pattern)
    if ".dpc" not in entries:
        entries.insert(0, ".dpc")
    return entries


def _build_dpc_section(context) -> str:
    """生成 .gitignore 中的 .dpc 屏蔽规则段落。"""
    lines = [f"{DPC_SECTION_MARKER}<自动同步，勿手动修改>==="]
    lines.extend(_get_dpc_entries(context))
    return "\n".join(lines) + "\n"


def _merge_dpc_section(existing: str, section: str) -> str:
    """将 .dpc 段落合并进已有 .gitignore<有则更新，无则追加>。"""
    if DPC_SECTION_MARKER not in existing:
        return existing.rstrip("\n") + "\n\n" + section
    start = existing.index(DPC_SECTION_MARKER)
    next_marker = existing.find("# ===", start + len(DPC_SECTION_MARKER))
    if next_marker == -1:
        next_marker = len(existing)
    return existing[:start].rstrip("\n") + "\n\n" + section + existing[next_marker:].lstrip("\n")


def _write_gitignore(context) -> Dict[str, Any]:
    """写入 .gitignore：合并 .dpc 屏蔽规则，新文件追加通用忽略模板。"""
    path = Path(context.work_directory) / ".gitignore"
    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except (OSError, PermissionError) as e:
            context.log_warning(f"读取 .gitignore 失败: {e}")
    content = _merge_dpc_section(existing, _build_dpc_section(context))
    if not existing:
        content += "\n" + "\n".join(_COMMON_IGNORES) + "\n"
    try:
        path.write_text(content, encoding="utf-8")
    except (OSError, PermissionError) as e:
        context.log_warning(f"写入 .gitignore 失败: {e}")
        return {"error": f"写入 .gitignore 失败: {e}"}
    count = len(_get_dpc_entries(context))
    context.log_info(f".gitignore 已更新，同步 {count} 条 .dpc 屏蔽规则")
    return {"success": True, "message": f".gitignore 已更新<同步 {count} 条 .dpc 屏蔽规则>"}


def _gitignore_exists(context) -> bool:
    """检查工作目录是否存在 .gitignore。"""
    return (Path(context.work_directory) / ".gitignore").exists()


skill_info = {
    "name": "git",
    "description": "Git 版本控制技能，可初始化仓库、暂存文件、提交更改、查看状态与历史。创建 .gitignore 时会自动同步 .dpc 屏蔽规则。",
    "functions": {
        "git_init": {
            "description": "在工作目录初始化 Git 仓库，并自动创建 .gitignore<同步 .dpc 屏蔽规则>。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "git_status": {
            "description": "查看工作目录的 Git 状态，显示暂存区与工作区的变更。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        "git_diff": {
            "description": "查看未暂存的更改差异。path 可限定查看单个文件，省略则查看全部更改。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要查看差异的文件路径<可选>，省略则查看全部更改"}
                },
                "required": []
            }
        },
        "git_add": {
            "description": "暂存文件，多个路径用逗号分隔。被 .dpc 屏蔽的路径会自动跳过。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "string", "description": "要暂存的路径，多个用逗号分隔，如 'main.py, modules/chat.py'"}
                },
                "required": ["paths"]
            }
        },
        "git_commit": {
            "description": "提交暂存的更改。提交信息必须使用英文，只描述更改内容，不携带版本号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "英文提交信息，如 'feat: add user login'"}
                },
                "required": ["message"]
            }
        },
        "git_log": {
            "description": "查看提交历史，max_count 控制显示条数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_count": {"type": "integer", "description": "显示提交条数，默认为 10"}
                },
                "required": []
            }
        },
        "create_gitignore": {
            "description": "创建或更新 .gitignore，自动从 .dpc 屏蔽规则获取内容并添加<已有文件则更新其中的 .dpc 段落>。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
}


def git_init(context) -> Dict[str, Any]:
    """在工作目录初始化 Git 仓库并生成 .gitignore。"""
    try:
        result = _run_git(context, ["init"])
        if not result.get("success"):
            return {
                **result,
                "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "init"}, {"text": "Error", "style": "red"}]},
            }
        gi_result = _write_gitignore(context)
        messages = ["Git 仓库已初始化"]
        if gi_result.get("success"):
            messages.append(gi_result["message"])
        else:
            messages.append(gi_result.get("error", "生成 .gitignore 失败"))
        return {
            "success": True,
            "message": "，".join(messages),
            "gitignore": gi_result.get("success", False),
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "init"}]},
        }
    except Exception as e:
        return {"error": f"初始化 Git 仓库失败: {e}", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "init"}, {"text": "Error", "style": "red"}]}}


def git_status(context) -> Dict[str, Any]:
    """查看工作目录的 Git 状态。"""
    result = _run_git(context, ["status", "--short"])
    if result.get("success"):
        status_text = result.get("stdout") or "<工作区干净，无未提交更改>"
        return {
            "success": True,
            "status": status_text,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "status"}]},
        }
    return {
        **result,
        "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "status"}, {"text": "Error", "style": "red"}]},
    }


def git_diff(context, path: str = None) -> Dict[str, Any]:
    """查看未暂存的更改差异。"""
    args = ["diff"]
    if path and path.strip():
        # -- 分隔符防止路径以 - 开头被当作 git 选项
        args += ["--", path.strip()]
    result = _run_git(context, args)
    if result.get("success"):
        diff_text = result.get("stdout") or "<无未暂存的更改>"
        return {
            "success": True,
            "diff": diff_text,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"diff {path or ''}".strip()}]},
        }
    return {
        **result,
        "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "diff"}, {"text": "Error", "style": "red"}]},
    }


def git_add(context, paths: str) -> Dict[str, Any]:
    """暂存文件，被 .dpc 屏蔽的路径自动跳过。"""
    path_list = [p.strip() for p in (paths or "").split(",") if p.strip()]
    if not path_list:
        return {"error": "请指定要暂存的路径", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "add"}, {"text": "Error", "style": "red"}]}}

    allowed, blocked = context.filter_allowed_paths(path_list)
    if blocked:
        context.log_warning(f"跳过被 .dpc 屏蔽的路径: {blocked}")
    if not allowed:
        return {
            "error": f"所有指定路径均被 .dpc 屏蔽: {blocked}",
            "blocked": blocked,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "add"}, {"text": "Error", "style": "red"}]},
        }

    # -- 分隔符防止路径以 - 开头被当作 git 选项
    result = _run_git(context, ["add", "--", *allowed])
    if result.get("success"):
        message = f"已暂存 {len(allowed)} 个路径"
        if blocked:
            message += f"，跳过被屏蔽: {', '.join(blocked)}"
        return {
            "success": True,
            "added": allowed,
            "blocked": blocked,
            "message": message,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"add {', '.join(allowed)}"}]},
        }
    return {
        **result,
        "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "add"}, {"text": "Error", "style": "red"}]},
    }


def git_commit(context, message: str, confirmed: bool = False) -> Dict[str, Any]:
    """提交暂存的更改<提交前需用户确认>。"""
    message = (message or "").strip()
    if not message:
        return {"error": "提交信息不能为空", "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "commit"}, {"text": "Error", "style": "red"}]}}
    if not confirmed:
        return {
            "requires_confirmation": True,
            "message": f"确认提交？提交信息: {message}",
            "action": "git_commit",
            "work_directory": context.work_directory,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"commit {message}", "style": "yellow"}]},
        }

    result = _run_git(context, ["commit", "-m", message])
    if result.get("success"):
        return {
            "success": True,
            "message": "提交成功",
            "commit": result.get("stdout"),
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"commit {message}"}]},
        }
    return {
        **result,
        "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "commit"}, {"text": "Error", "style": "red"}]},
    }


def git_log(context, max_count: int = 10) -> Dict[str, Any]:
    """查看提交历史。"""
    try:
        count = max(1, int(max_count))
    except (TypeError, ValueError):
        count = 10
    result = _run_git(context, ["log", "--oneline", "-n", str(count)])
    if result.get("success"):
        log_text = result.get("stdout") or "<暂无提交历史>"
        return {
            "success": True,
            "log": log_text,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": f"log -{count}"}]},
        }
    return {
        **result,
        "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": "log"}, {"text": "Error", "style": "red"}]},
    }


def create_gitignore(context, confirmed: bool = False) -> Dict[str, Any]:
    """创建或更新 .gitignore，自动同步 .dpc 屏蔽规则。"""
    if _gitignore_exists(context) and not confirmed:
        return {
            "requires_confirmation": True,
            "message": ".gitignore 已存在，确认更新其中的 .dpc 屏蔽规则段落？",
            "action": "create_gitignore",
            "work_directory": context.work_directory,
            "user_output": {"label": OUTPUT_LABEL, "parts": [{"text": ".gitignore"}, {"text": "?", "style": "yellow"}]},
        }
    result = _write_gitignore(context)
    if result.get("success"):
        result["user_output"] = {"label": OUTPUT_LABEL, "parts": [{"text": ".gitignore"}]}
    else:
        result["user_output"] = {"label": OUTPUT_LABEL, "parts": [{"text": ".gitignore"}, {"text": "Error", "style": "red"}]}
    return result
