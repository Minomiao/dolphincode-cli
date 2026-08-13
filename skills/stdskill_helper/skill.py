"""
标准技能助手（stdskill_helper）。

程序化辅助标准技能（Agent Skills / SKILL.md 格式）的创建与安装：
- 创建：生成合法 frontmatter，写入 stdskills/<技能名>/SKILL.md
- 安装：从外部来源（GitHub 合集、Codex 技能目录、整包仓库）自动识别并复制到 stdskills/
- 列出：扫描 stdskills/ 下已安装的标准技能

与 standard_skill_loader 的加载约定保持一致：frontmatter name 去重、
跳过脚手架目录（.git/.github/.claude-plugin 等）。
"""
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any

_SKILL_NAME_RE = re.compile(r"^[a-z0-9-]+$")
# 安装时忽略的脚手架目录/文件
_SCAFFOLD_DIRS = {".git", ".github", ".claude-plugin", "__pycache__",
                  ".venv", "venv", "node_modules", ".idea", ".vscode", "dist", "build"}
_SCAFFOLD_FILES = {".DS_Store", ".gitkeep", ".gitattributes", ".gitignore"}


def _stdskills_dir() -> Path:
    """返回标准技能目录（项目根目录下的 stdskills/）。"""
    from modules import bootstrap as app_paths
    return Path(os.path.join(app_paths.PROJECT_ROOT, "stdskills"))


def _parse_skill_md(content: str) -> Dict[str, Any]:
    """解析 SKILL.md，返回 {name, description, body}。"""
    if not content.startswith("---"):
        return {"name": None, "description": None, "body": content}
    end_marker = content.find("\n---", 3)
    if end_marker == -1:
        raise ValueError("SKILL.md frontmatter 缺少结束标记 '---'")
    import yaml
    frontmatter = yaml.safe_load(content[3:end_marker].strip()) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("frontmatter 必须是 YAML 映射")
    return {
        "name": frontmatter.get("name"),
        "description": frontmatter.get("description"),
        "body": content[end_marker + 4:].strip(),
    }


def _valid_name(name: str) -> bool:
    """校验标准技能名：小写字母/数字/连字符，不以连字符开头或结尾，长度 ≤ 64。"""
    return bool(_SKILL_NAME_RE.match(name)) and not name.startswith("-") \
        and not name.endswith("-") and len(name) <= 64


def _existing_skill_names() -> Dict[str, Path]:
    """扫描 stdskills/ 下所有 SKILL.md，返回 {技能名: SKILL.md 路径}（跳过 _/. 开头的目录）。"""
    names = {}
    skills_dir = _stdskills_dir()
    if not skills_dir.exists():
        return names
    for skill_file in skills_dir.rglob("SKILL.md"):
        rel_parts = skill_file.parent.relative_to(skills_dir).parts
        if any(p.startswith(("_", ".")) for p in rel_parts):
            continue
        try:
            parsed = _parse_skill_md(skill_file.read_text(encoding="utf-8"))
        except Exception:
            parsed = {"name": None}
        names.setdefault(parsed.get("name") or skill_file.parent.name, skill_file)
    return names


def _err(context, message: str) -> Dict[str, Any]:
    """构造错误返回并记录日志。"""
    context.log_warning(message)
    return {
        "success": False,
        "error": message,
        "user_output": {"label": "skills", "parts": [{"text": message, "style": "red"}]},
    }


skill_info = {
    "name": "stdskill_helper",
    "description": "标准技能助手：程序化创建 SKILL.md 标准技能到项目 stdskills/ 目录，"
                   "或将外部标准技能（GitHub 合集、Codex 技能目录、整包仓库）自动安装到 stdskills/。"
                   "也支持列出已安装的标准技能。",
    "functions": {
        "create_skill": {
            "description": "创建一个新的标准技能（Agent Skills / SKILL.md 格式）到项目 stdskills/ 目录。"
                           "自动生成合法 frontmatter，校验技能名格式并做重名检查。"
                           "新技能需重启 Dolphin 后生效，工具名为 stdskill_<技能名>。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "技能名：小写字母、数字、连字符组成（如 my-skill），"
                                                              "不得含下划线或空格，不能以连字符开头或结尾，长度不超过 64"},
                    "description": {"type": "string", "description": "一句话说明何时使用该技能（模型决定是否调用的唯一依据），"
                                                                     "应包含触发场景与适用任务类型"},
                    "content": {"type": "string", "description": "SKILL.md 正文（不含 frontmatter），写给模型看的逐步操作指南；"
                                                                 "若传入完整 SKILL.md 文本（以 --- 开头）则原样采用"},
                    "overwrite": {"type": "boolean", "description": "同名技能已存在时是否覆盖，默认 false"}
                },
                "required": ["name", "description", "content"]
            }
        },
        "install_skill": {
            "description": "从外部路径自动安装标准技能到 stdskills/ 目录。支持三种来源："
                           "单个技能文件夹（直接含 SKILL.md）、技能合集目录（含多个 skills/<名>/SKILL.md）、"
                           "整包仓库根目录（下载解压后的 xxx-main/）。"
                           "自动解析 frontmatter 技能名、跳过仓库脚手架（.git/.github/.claude-plugin 等）、"
                           "对已存在的技能自动去重跳过。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "外部技能来源的绝对路径：单个技能文件夹、"
                                                                "技能合集目录或整包仓库根目录"}
                },
                "required": ["source"]
            }
        },
        "list_skills": {
            "description": "列出 stdskills/ 目录下已安装的所有标准技能（技能名、描述、来源文件夹）。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
}


def create_skill(context, name: str, description: str, content: str,
                 overwrite: bool = False) -> Dict[str, Any]:
    """创建标准技能到 stdskills/。"""
    try:
        name = (name or "").strip()
        description = (description or "").strip()
        content = (content or "").strip()

        if not _valid_name(name):
            return _err(context, f"技能名不合法: '{name}'，须为小写字母/数字/连字符，"
                                 f"不以连字符开头或结尾，长度不超过 64")
        if not description:
            return _err(context, "description 不能为空")
        if not content:
            return _err(context, "content 不能为空")

        skills_dir = _stdskills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)

        existing = _existing_skill_names()
        if name in existing and not overwrite:
            return _err(context, f"标准技能 '{name}' 已存在（来源: {existing[name].parent}），"
                                 f"如需覆盖请设置 overwrite=True")

        # 传入完整 SKILL.md 则原样采用，否则自动生成 frontmatter
        if content.startswith("---"):
            skill_text = content
        else:
            skill_text = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n"

        skill_folder = skills_dir / name
        skill_file = skill_folder / "SKILL.md"
        skill_folder.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(skill_text, encoding="utf-8")

        context.log_info(f"创建标准技能成功: {name} -> {skill_file}")
        return {
            "success": True,
            "skill": name,
            "file": str(skill_file),
            "note": "新技能需重启 Dolphin 后生效，工具名为 stdskill_<技能名>",
            "user_output": {"label": "skills", "parts": [{"text": f"创建技能 {name}", "style": "green"}]},
        }
    except PermissionError as e:
        return _err(context, f"无权限写入 stdskills: {e}")
    except OSError as e:
        return _err(context, f"写入 stdskills 失败: {e}")
    except Exception as e:
        return _err(context, f"创建标准技能失败: {e}")


def install_skill(context, source: str) -> Dict[str, Any]:
    """从外部路径自动安装标准技能到 stdskills/。"""
    try:
        src = Path(source).resolve()
        if not src.exists():
            return _err(context, f"来源路径不存在: {src}")
        if not src.is_dir():
            return _err(context, f"来源必须是文件夹: {src}")

        skills_dir = _stdskills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        try:
            src.relative_to(skills_dir)
            return _err(context, f"来源路径已在 stdskills/ 内，无需安装: {src}")
        except ValueError:
            pass

        # 定位所有 SKILL.md：单个技能文件夹直接命中，合集/整包递归查找
        candidate_files = []
        direct = src / "SKILL.md"
        if direct.exists():
            candidate_files.append(direct)
        candidate_files.extend(p for p in src.rglob("SKILL.md") if p != direct)
        if not candidate_files:
            return _err(context, f"来源中未找到任何 SKILL.md: {src}")

        existing = _existing_skill_names()
        installed, skipped, failed = [], [], []
        for skill_file in candidate_files:
            skill_folder = skill_file.parent
            # 跳过脚手架目录（.git/.github/.claude-plugin 等）
            rel_parts = skill_folder.relative_to(src).parts
            if any(p.startswith(("_", ".")) or p in _SCAFFOLD_DIRS for p in rel_parts):
                continue
            try:
                parsed = _parse_skill_md(skill_file.read_text(encoding="utf-8"))
            except Exception as e:
                failed.append(f"{skill_folder.name}: 解析失败 {e}")
                continue
            name = (parsed.get("name") or skill_folder.name).strip()
            if not _valid_name(name):
                failed.append(f"{skill_folder.name}: 技能名不合法 '{name}'")
                continue
            if name in existing or name in installed:
                skipped.append(name)
                continue
            target = skills_dir / name
            shutil.copytree(skill_folder, target,
                            ignore=shutil.ignore_patterns(*_SCAFFOLD_DIRS, *_SCAFFOLD_FILES))
            installed.append(name)
            context.log_info(f"安装标准技能成功: {name} -> {target}")

        message = f"安装完成: 新增 {len(installed)}，跳过 {len(skipped)}，失败 {len(failed)}"
        context.log_info(message)
        return {
            "success": True,
            "installed": installed,
            "skipped": skipped,
            "failed": failed,
            "message": message,
            "note": "新技能需重启 Dolphin 后生效，工具名为 stdskill_<技能名>",
            "user_output": {"label": "skills", "parts": [{"text": message, "style": "green"}]},
        }
    except PermissionError as e:
        return _err(context, f"无权限写入 stdskills: {e}")
    except OSError as e:
        return _err(context, f"复制技能失败: {e}")
    except Exception as e:
        return _err(context, f"安装标准技能失败: {e}")


def list_skills(context) -> Dict[str, Any]:
    """列出 stdskills/ 下已安装的标准技能。"""
    try:
        existing = _existing_skill_names()
        items = []
        for name, skill_file in sorted(existing.items()):
            try:
                parsed = _parse_skill_md(skill_file.read_text(encoding="utf-8"))
                description = parsed.get("description", "")
            except Exception as e:
                description = f"（读取失败: {e}）"
            items.append({
                "name": name,
                "description": description,
                "folder": str(skill_file.parent),
            })
        message = f"已安装 {len(items)} 个标准技能"
        return {
            "success": True,
            "count": len(items),
            "skills": items,
            "message": message,
            "user_output": {"label": "skills", "parts": [{"text": message, "style": "green"}]},
        }
    except Exception as e:
        return _err(context, f"列出标准技能失败: {e}")
