"""
标准技能加载器。
加载符合 Agent Skills 标准的技能，与现有 skill.py 体系完全分离：
- 目录：stdskills/ 下任意层级包含技能定义文件的文件夹（自动递归识别，支持合集仓库整包放入）
- 定义文件支持三种，同一文件夹按优先级取第一个：
  - SKILL.md：YAML frontmatter（name、description）+ Markdown 正文
  - skill.yaml / skill.yml：纯 YAML 定义（name、description、instructions/body）
- 每个标准技能注册为一个工具 stdskill_<skill_name>，调用时返回正文（按需注入）
- 技能名允许包含连字符，工具名内不做转换
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional, List

import yaml

from modules.logger import get_logger
from modules import bootstrap as app_paths
from modules.bootstrap import constants
from .base_loader import BaseSkillLoader

log = get_logger("Dolphin.standard_skill_loader")

# 技能定义文件，按优先级顺序查找（同一文件夹只取第一个）
_DEFINITION_FILES = ("SKILL.md", "skill.yaml", "skill.yml")


class StandardSkillLoader(BaseSkillLoader):
    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(app_paths.PROJECT_ROOT, "stdskills")
        self.skills_dir = Path(skills_dir)
        super().__init__()
        # 聚合视图：注册名 → {members: [子技能名], kind: "pack"/"single"}
        # 合集仓库（同来源多成员）注册为一个工具；根目录单技能保持独立
        self.packs: Dict[str, Dict[str, Any]] = {}
        self._load_skills()
        log.info(f"StandardSkillLoader 初始化完成: {len(self.skills)} 个标准技能, "
                 f"{len(self.packs)} 个注册条目, {len(self.failed_skills)} 个失败")
        if self.failed_skills:
            log.warning(f"加载失败的标准技能: {list(self.failed_skills.keys())}")
            for skill_name, error in self.failed_skills.items():
                log.warning(f"  - {skill_name}: {error}")

    def _tool_prefix(self) -> str:
        return constants.TOOL_PREFIX_STD_SKILL

    def _config_section(self) -> str:
        return "stdskills"

    def _load_skills(self):
        self.skills = {}
        self.failed_skills = {}
        self._scan_into(self.skills, self.failed_skills)
        self.packs = self._compute_packs(self.skills)
        self._rebuild_tool_lookup()

    def reload_skills(self) -> Dict[str, Any]:
        """原子热重载：局部重建后一次性替换，失败时保留现有技能。

        供 stdskill_helper 安装/创建标准技能后调用，使新技能
        在下一轮对话即可用（chat_stream 每轮刷新工具列表）。
        """
        new_skills: Dict[str, Any] = {}
        new_failed: Dict[str, str] = {}
        try:
            self._scan_into(new_skills, new_failed)
            new_packs = self._compute_packs(new_skills)
        except Exception as e:
            log.error(f"标准技能热重载失败，保留现有 {len(self.skills)} 个技能: {e}")
            return {
                "success": False,
                "error": str(e),
                "loaded_count": len(self.skills),
                "failed_count": len(self.failed_skills),
            }
        self.skills = new_skills
        self.failed_skills = new_failed
        self.packs = new_packs
        self._rebuild_tool_lookup()
        log.info(f"标准技能热重载完成: {len(new_skills)} 个技能, {len(new_packs)} 个注册条目")
        return {
            "success": True,
            "loaded_count": len(new_skills),
            "failed_count": len(new_failed),
            "failed_skills": list(new_failed),
        }

    def _scan_into(self, skills_out: Dict[str, Any], failed_out: Dict[str, str]):
        """扫描 skills_dir 并把结果填充到传入字典（不触碰实例状态，供原子重载）。"""
        if not self.skills_dir.exists():
            log.info(f"标准技能目录不存在，创建目录: {self.skills_dir}")
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            return

        folders = [self.skills_dir] + [p for p in self.skills_dir.rglob("*") if p.is_dir()]
        for skill_folder in folders:
            if skill_folder != self.skills_dir:
                # 跳过名称以 _ 或 . 开头的目录（含祖先目录，如 .git、_draft、.claude-plugin）
                rel_parts = skill_folder.relative_to(self.skills_dir).parts
                if any(part.startswith(("_", ".")) for part in rel_parts):
                    continue

            try:
                self._load_skill_folder(skill_folder, skills_out)
            except (FileNotFoundError, PermissionError) as e:
                error_msg = f"文件访问错误: {str(e)}"
                failed_out[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")
            except (yaml.YAMLError, KeyError, ValueError) as e:
                error_msg = f"定义文件解析错误: {str(e)}"
                failed_out[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")
            except Exception as e:
                error_msg = f"{str(e)}"
                failed_out[skill_folder.name] = error_msg
                log.error(f"加载标准技能 {skill_folder.name} 失败: {error_msg}")

    def _load_skill_folder(self, skill_folder: Path, skills_out: Dict[str, Any]):
        log.debug(f"加载标准技能文件夹: {skill_folder.name}")
        skill_file = self._find_definition_file(skill_folder)

        if skill_file is None:
            log.debug(f"跳过 {skill_folder.name}: 没有 SKILL.md / skill.yaml / skill.yml")
            return

        content = skill_file.read_text(encoding="utf-8")
        if skill_file.name.lower().endswith((".yaml", ".yml")):
            name, description, body = self._parse_skill_yaml(content)
        else:
            name, description, body = self._parse_skill_md(content)

        if not name:
            name = skill_folder.name
        if not description:
            description = f"标准技能 {name}"

        if name in skills_out:
            log.warning(f"标准技能 {name} 已存在（重复来源: {skill_folder}），跳过")
            return

        # 来源：合集仓库取顶层文件夹名，根目录单技能取自身名
        rel_parts = skill_folder.relative_to(self.skills_dir).parts
        source = rel_parts[0] if len(rel_parts) > 1 else name

        skills_out[name] = {
            "name": name,
            "description": description,
            "folder": str(skill_folder),
            "source": source,
            "body": body,
            "functions": {},
        }
        log.info(f"标准技能加载成功: {name}")

    def _find_definition_file(self, skill_folder: Path) -> Optional[Path]:
        """按优先级返回技能定义文件（SKILL.md / skill.yaml / skill.yml），找不到返回 None。"""
        for fname in _DEFINITION_FILES:
            skill_file = skill_folder / fname
            if skill_file.is_file():
                return skill_file
        return None

    def _parse_skill_yaml(self, content: str) -> tuple:
        """解析 skill.yaml / skill.yml，返回 (name, description, body)。

        格式：YAML 顶层映射，name 为技能名，description 为技能说明，
        instructions（或 body）为正文使用说明。
        """
        data = yaml.safe_load(content) or {}
        if not isinstance(data, dict):
            raise ValueError("skill.yaml 必须是 YAML 映射")

        return (data.get("name"),
                data.get("description"),
                data.get("instructions") or data.get("body") or "")

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

    def _build_packs(self):
        """按来源聚合注册条目（启动路径，结果写入 self.packs）。"""
        self.packs = self._compute_packs(self.skills)

    def _compute_packs(self, skills: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """按来源聚合注册条目。

        同来源成员数 > 1 的合集注册为一个 pack 工具（stdskill_<合集名>，
        携带 skill 枚举参数）；单成员来源保持独立（stdskill_<技能名>，无参数）。
        """
        groups: Dict[str, List[str]] = {}
        for name, info in skills.items():
            source = info.get("source") or name
            groups.setdefault(source, []).append(name)

        packs: Dict[str, Dict[str, Any]] = {}
        for source, members in groups.items():
            if len(members) > 1:
                packs[source] = {"members": sorted(members), "kind": "pack"}
            else:
                member = members[0]
                packs[member] = {"members": [member], "kind": "single"}
        return packs

    def _rebuild_tool_lookup(self):
        """标准技能按 pack 注册：stdskill_<合集名> 或 stdskill_<技能名>。"""
        self._tool_lookup = {
            f"{self._tool_prefix()}{pack_name}": (pack_name, "run")
            for pack_name in self.packs
        }

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        return text if len(text) <= width else text[:width] + "…"

    def _pack_description(self, pack_name: str, members: List[str], max_len: int = 600) -> str:
        """合集工具描述：子技能清单（名称 + 截断后的单行描述）。"""
        lines = [
            f"- {n}: {self._truncate(self.skills[n].get('description', ''), 40)}"
            for n in members
        ]
        text = f"技能合集 {pack_name}，含 {len(members)} 个技能:\n" + "\n".join(lines)
        if len(text) > max_len:
            text = text[:max_len] + "…"
        return text

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """返回标准技能的工具定义。

        single：无参数工具；pack：携带 skill 枚举参数的合并工具。
        启停为组级：合集按合集名过滤，单技能按技能名过滤。
        """
        from modules.main_server import config
        config_section = config.load_config().get(self._config_section(), {})

        tools = []
        for pack_name, pack in self.packs.items():
            if not config_section.get(pack_name, True):
                continue

            members = pack["members"]
            if pack["kind"] == "single":
                description = self.skills[members[0]].get("description", "")
                parameters = {"type": "object", "properties": {}, "required": []}
            else:
                description = self._pack_description(pack_name, members)
                parameters = {
                    "type": "object",
                    "properties": {
                        "skill": {
                            "type": "string",
                            "enum": members,
                            "description": "要执行的技能名",
                        }
                    },
                    "required": ["skill"],
                }

            tools.append({
                "type": "function",
                "function": {
                    "name": f"{self._tool_prefix()}{pack_name}",
                    "description": description,
                    "parameters": parameters,
                }
            })
        return tools

    def get_tool_names(self) -> List[str]:
        return [f"{self._tool_prefix()}{pack_name}" for pack_name in self.packs]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用标准技能：返回正文供模型按指令执行。

        single 直接执行；pack 依据 skill 枚举参数选择子技能。
        """
        log.info(f"调用标准技能: {tool_name}, 参数: {arguments}")
        resolved = self._tool_lookup.get(tool_name)
        if resolved is None:
            log.error(f"标准技能不存在或未注册: {tool_name}")
            raise ValueError(f"标准技能不存在: {tool_name}")

        pack_name, _ = resolved
        pack = self.packs[pack_name]
        members = pack["members"]

        if pack["kind"] == "single":
            skill_name = members[0]
        else:
            skill_name = (arguments or {}).get("skill")
            if not skill_name:
                return {
                    "error": "缺少 skill 参数",
                    "available": members,
                    "hint": "请从 available 中选择要执行的技能",
                }
            if skill_name not in members:
                return {
                    "error": f"未知的技能: {skill_name}",
                    "available": members,
                }

        skill_info = self.skills[skill_name]
        display_name = skill_name if pack["kind"] == "single" else f"{pack_name}/{skill_name}"

        return {
            "success": True,
            "skill": display_name,
            "instructions": skill_info.get("body", ""),
            "folder": skill_info.get("folder", ""),
            "hint": "请阅读 instructions 并按步骤执行；如需运行 scripts/ 下的脚本，"
                    "请使用 powershell_executor 的 run_script 工具。",
            # 用户可见输出：终端显示为 [skills]<技能名>，并跳过 --工具调用/--结果 的全文刷屏
            "user_output": {"label": "skills", "parts": [{"text": display_name}]},
        }

    def list_skills(self) -> list:
        from modules.main_server import config
        std_config = config.load_config().get(self._config_section(), {})
        return [
            {
                "name": f"stdskill-{pack_name}",
                "description": (
                    self.skills[pack["members"][0]].get("description", "")
                    if pack["kind"] == "single"
                    else self._pack_description(pack_name, pack["members"])
                ),
                "functions": pack["members"],
                "enabled": std_config.get(pack_name, True)
            }
            for pack_name, pack in self.packs.items()
        ]

    def toggle_skill(self, skill_name: str, enabled: bool) -> Dict[str, Any]:
        from modules.main_server import config
        if skill_name.startswith("stdskill-"):
            original_skill_name = skill_name[len("stdskill-"):]
        else:
            original_skill_name = skill_name

        # 启停为组级：键为 pack 注册名（合集名或独立技能名）
        if original_skill_name not in self.packs:
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
