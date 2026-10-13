import os
import importlib.util
import traceback
from typing import Dict, Any, Optional
from pathlib import Path
from modules.logger import get_logger
from modules import bootstrap as app_paths
from modules.bootstrap import constants
from .base_loader import BaseSkillLoader

log = get_logger("Dolphin.skill_manager")


class SkillManager(BaseSkillLoader):
    def __init__(self, skills_dir: str = None):
        if skills_dir is None:
            skills_dir = os.path.join(app_paths.PROJECT_ROOT, "skills")
        self.skills_dir = Path(skills_dir)
        super().__init__()
        self._current_work_dir: Optional[str] = self._get_default_work_dir()
        self._load_skills()

    def _tool_prefix(self) -> str:
        return constants.TOOL_PREFIX_SKILL

    def _config_section(self) -> str:
        return "skills"

    def _load_skills(self):
        if not self.skills_dir.exists():
            log.info(f"技能目录不存在，创建目录: {self.skills_dir}")
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            self._rebuild_tool_lookup()
            return

        for skill_folder in self.skills_dir.iterdir():
            if not skill_folder.is_dir() or skill_folder.name.startswith("_"):
                continue

            try:
                self._load_skill_folder(skill_folder)
            except (FileNotFoundError, PermissionError) as e:
                error_msg = f"文件访问错误: {str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载技能 {skill_folder.name} 失败: {error_msg}")
            except SyntaxError as e:
                error_msg = f"技能脚本语法错误: {str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载技能 {skill_folder.name} 失败: {error_msg}")
            except ImportError as e:
                error_msg = f"技能依赖导入失败: {str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载技能 {skill_folder.name} 失败: {error_msg}")
            except Exception as e:
                error_msg = f"{str(e)}"
                self.failed_skills[skill_folder.name] = error_msg
                log.error(f"加载技能 {skill_folder.name} 失败: {error_msg}")
                log.debug(f"错误详情:\n{traceback.format_exc()}")

        self._rebuild_tool_lookup()

    def _load_skill_folder(self, skill_folder: Path):
        log.debug(f"加载技能文件夹: {skill_folder.name}")
        skill_file = skill_folder / "skill.py"

        if not skill_file.exists():
            log.debug(f"跳过 {skill_folder.name}: 没有 skill.py 文件")
            return

        spec = importlib.util.spec_from_file_location(
            f"skills.{skill_folder.name}.skill",
            skill_file
        )
        if spec is None or spec.loader is None:
            log.warning(f"无法创建模块规范: {skill_folder.name}")
            return

        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except SyntaxError as e:
            log.error(f"技能 {skill_folder.name} 存在语法错误: {e}")
            raise
        except ImportError as e:
            log.error(f"技能 {skill_folder.name} 导入依赖失败: {e}")
            raise
        except (FileNotFoundError, PermissionError) as e:
            log.error(f"技能 {skill_folder.name} 文件访问失败: {e}")
            raise
        except Exception as e:
            log.error(f"执行技能模块失败 {skill_folder.name}: {e}")
            raise

        if not hasattr(module, 'skill_info'):
            log.warning(f"技能 {skill_folder.name} 没有 skill_info 定义")
            return

        skill_info = module.skill_info

        if 'name' not in skill_info:
            skill_info['name'] = skill_folder.name

        if 'functions' in skill_info:
            for func_name, func_info in skill_info['functions'].items():
                if hasattr(module, func_name):
                    func_info['callable'] = getattr(module, func_name)
                else:
                    log.warning(f"技能 {skill_info['name']} 的函数 {func_name} 未找到")

        self.skills[skill_info['name']] = skill_info
        log.info(f"技能加载成功: {skill_info['name']}")

    def list_skills(self) -> list:
        from modules.main_server import config
        skills_config = config.load_config().get('skills', {})
        return [
            {
                "name": skill_name,
                "description": skill_info.get('description', ''),
                "functions": list(skill_info.get('functions', {}).keys()),
                "enabled": skills_config.get(skill_name, True)
            }
            for skill_name, skill_info in self.skills.items()
        ]

    def toggle_skill(self, skill_name: str, enabled: bool) -> Dict[str, Any]:
        from modules.main_server import config
        if skill_name not in self.skills:
            return {"error": f"技能不存在: {skill_name}"}

        # 读-改-写模式：asyncio 单线程模型中无 await 切换点，不存在竞态条件
        current_config = config.load_config()
        if 'skills' not in current_config:
            current_config['skills'] = {}

        current_config['skills'][skill_name] = enabled
        config.save_config(current_config)

        return {
            "success": True,
            "skill": skill_name,
            "enabled": enabled,
            "message": f"技能 '{skill_name}' 已{'启用' if enabled else '禁用'}"
        }


_skill_manager = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager
