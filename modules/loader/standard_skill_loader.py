"""
标准技能加载器。
加载符合 Agent Skills 标准（SKILL.md）的技能，与现有 skill.py 体系完全分离：
- 目录：stdskills/ 下任意层级包含 SKILL.md 的文件夹（自动递归识别，支持合集仓库整包放入）
- SKILL.md 以 YAML frontmatter 开头（name、description），正文为使用说明
- 每个标准技能注册为一个工具 stdskill_<skill_name>，调用时返回 SKILL.md 正文（按需注入）
- 技能名允许包含连字符，工具名内不做转换
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

import yaml

from modules.logger import get_logger
from modules import bootstrap as app_paths
from .base_loader import BaseSkillLoader

log = get_logger("Dolphin.standard_skill_loader")


class StandardSkillLoader(BaseSkillLoader):
    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(app_paths.PROJECT_ROOT, "stdskills")
        self.skills_dir = Path(skills_dir)
        super().__init__()
        self._load_skills()
        log.info(f"StandardSkillLoader 初始化完成: {len(self.skills)} 个标准技能加载成功, "
                 f"{len(self.failed_skills)} 个失败")
        if self.failed_skills:
            log.warning(f"加载失败的标准技能: {list(self.failed_skills.keys())}")
            for skill_name, error in self.failed_skills.items():
                log.warning(f"  - {skill_name}: {error}")

    def _tool_prefix(self) -> str:
        return "stdskill_"

    def _config_section(self) -> str:
        return "stdskills"

    def _load_skills(self):
        if not self.skills_dir.exists():
            log.info(f"标准技能目录不存在，创建目录: {self.skills_dir}")
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            return

        for skill_file in self.skills_dir.rglob("SKILL.md"):
            skill_folder = skill_file.parent
            # 跳过名称以 _ 或 . 开头的目录（含祖先目录，如 .git、_draft、.claude-plugin）
            rel_parts = skill_folder.relative_to(self.skills_dir).parts
            if any(part.startswith(("_", ".")) for part in rel_parts):
                continue

            try:
                self._load_skill_folder(skill_folder)
            except (FileNotFoundError, PermissionError) as e:
                error_msg = f"文件访问错误: {str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")
            except (yaml.YAMLError, KeyError, ValueError) as e:
                error_msg = f"SKILL.md 解析错误: {str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")
            except Exception as e:
                error_msg = f"{str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")

    def _load_skill_folder(self, skill_folder: Path):
        log.debug(f"加载标准技能文件夹: {skill_folder.name}")
        skill_file = skill_folder / "SKILL.md"

        if not skill_file.exists():
            log.debug(f"跳过 {skill_folder.name}: 没有 SKILL.md 文件")
            return

        content = skill_file.read_text(encoding="utf-8")
        name, description, body = self._parse_skill_md(content)

        if not name:
            name = skill_folder.name
        if not description:
            description = f"标准技能 {name}"

        if name in self.skills:
            log.warning(f"标准技能 {name} 已存在（重复来源: {skill_folder}），跳过")
            return

        self.skills[name] = {
            "name": name,
            "description": description,
            "folder": str(skill_folder),
            "body": body,
            "functions": {},
        }
        log.info(f"标准技能加载成功: {name}")

    def _parse_skill_md(self, content: str) -> tuple:
        """解析 SKILL.md，返回 (name, description, body)。

        格式：文件开头为 --- 包裹的 YAML frontmatter，其后为 Markdown 正文。
        """
        if not content.startswith("---"):
            return None, None, content

        end_marker = content.find("\n---", 3)
        if end_marker == -1:
            raise ValueError("SKILL.md frontmatter 缺少结束标记 '---'")

        frontmatter_text = content[3:end_marker].strip()
        body = content[end_marker + 4:].strip()

        frontmatter = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(frontmatter, dict):
            raise ValueError("frontmatter 必须是 YAML 映射")

        return frontmatter.get("name"), frontmatter.get("description"), body

    def _resolve_skill_name(self, tool_name: str) -> Optional[tuple]:
        """从工具名解析出 (skill_name, action)。

        标准技能工具名为 stdskill_<skill_name>，技能名允许包含连字符，
        因此直接截取前缀后的部分作为技能名，无需按 "_" 回溯匹配。
        """
        prefix = self._tool_prefix()
        if not tool_name.startswith(prefix):
            return None
        skill_name = tool_name[len(prefix):]
        if skill_name not in self.skills:
            return None
        return skill_name, "run"

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """返回标准技能的工具定义（每个技能一个工具，无参数）。"""
        from modules.main_server import config
        config_section = config.load_config().get(self._config_section(), {})

        tools = []
        for skill_name, skill_info in self.skills.items():
            if not config_section.get(skill_name, True):
                continue
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{self._tool_prefix()}{skill_name}",
                    "description": skill_info.get('description', ''),
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            })
        return tools

    def get_tool_names(self) -> List[str]:
        return [f"{self._tool_prefix()}{name}" for name in self.skills]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用标准技能：返回 SKILL.md 正文供模型按指令执行。"""
        log.info(f"调用标准技能: {tool_name}, 参数: {arguments}")
        resolved = self._resolve_skill_name(tool_name)
        if resolved is None:
            log.error(f"找不到对应的标准技能: {tool_name}")
            raise ValueError(f"找不到对应的标准技能: {tool_name}")

        skill_name, _ = resolved
        skill_info = self.skills[skill_name]

        return {
            "success": True,
            "skill": skill_name,
            "instructions": skill_info.get("body", ""),
            "folder": skill_info.get("folder", ""),
            "hint": "请阅读 instructions 并按步骤执行；如需运行 scripts/ 下的脚本，"
                    "请使用 powershell_executor 的 run_script 工具。",
        }

    def list_skills(self) -> list:
        from modules.main_server import config
        std_config = config.load_config().get(self._config_section(), {})
        return [
            {
                "name": f"stdskill-{skill_name}",
                "description": skill_info.get('description', ''),
                "functions": [],
                "enabled": std_config.get(skill_name, True)
            }
            for skill_name, skill_info in self.skills.items()
        ]

    def toggle_skill(self, skill_name: str, enabled: bool) -> Dict[str, Any]:
        from modules.main_server import config
        if skill_name.startswith("stdskill-"):
            original_skill_name = skill_name[len("stdskill-"):]
        else:
            original_skill_name = skill_name

        if original_skill_name not in self.skills:
            return {"error": f"标准技能不存在: {skill_name}"}

        current_config = config.load_config()
        if self._config_section() not in current_config:
            current_config[self._config_section()] = {}

        current_config[self._config_section()][original_skill_name] = enabled
        config.save_config(current_config)

        return {
            "success": True,
            "skill": skill_name,
            "enabled": enabled,
            "message": f"标准技能 '{skill_name}' 已{'启用' if enabled else '禁用'}"
        }


_standard_skill_loader = None


def get_standard_skill_loader() -> StandardSkillLoader:
    global _standard_skill_loader
    if _standard_skill_loader is None:
        _standard_skill_loader = StandardSkillLoader()
    return _standard_skill_loader
