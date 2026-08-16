import os
import json
import importlib.util
import traceback
import zipfile
import tempfile
from typing import Dict, Any, Optional
from pathlib import Path
from modules.logger import get_logger
from modules import bootstrap as app_paths
from .base_loader import BaseSkillLoader

log = get_logger("Dolphin.plugin_skill_loader")


class PluginSkillLoader(BaseSkillLoader):
    def __init__(self, plugins_dir: str = None):
        if plugins_dir is None:
            plugins_dir = os.path.join(app_paths.PROJECT_ROOT, "plugins")
        self.plugins_dir = Path(plugins_dir)
        super().__init__()
        self._load_skills()
        log.info(f"PluginSkillLoader 初始化完成: {len(self.skills)} 个插件技能加载成功, {len(self.failed_skills)} 个失败")
        if self.failed_skills:
            log.warning(f"加载失败的插件技能: {list(self.failed_skills.keys())}")
            for skill_name, error in self.failed_skills.items():
                log.warning(f"  - {skill_name}: {error}")

    def _tool_prefix(self) -> str:
        return "plugin_"

    def _config_section(self) -> str:
        return "plugins"

    def _load_skills(self):
        if not self.plugins_dir.exists():
            log.info(f"插件目录不存在，创建目录: {self.plugins_dir}")
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            return

        for zip_file in self.plugins_dir.iterdir():
            if not zip_file.is_file() or not zip_file.name.endswith('.zip'):
                continue

            try:
                self._load_skill_from_zip(zip_file)
            except Exception as e:
                error_msg = f"{str(e)}"
                self.failed_skills[zip_file.name] = error_msg
                log.error(f"加载插件技能压缩包 {zip_file.name} 失败: {error_msg}")
                log.debug(f"错误详情:\n{traceback.format_exc()}")

    def _load_skill_from_zip(self, zip_file: Path):
        log.debug(f"加载插件技能压缩包: {zip_file.name}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_file, 'r') as zf:
                zf.extractall(temp_dir)

            temp_path = Path(temp_dir)

            # 首先尝试读取 manifest.json
            manifest_file = temp_path / 'manifest.json'
            if manifest_file.exists():
                try:
                    self._load_skill_with_manifest(temp_path, manifest_file, zip_file.name)
                    return
                except Exception as e:
                    log.warning(f"使用 manifest.json 加载失败，尝试旧方式: {e}")

            # 如果没有 manifest.json 或加载失败，使用旧的方式
            for root, dirs, files in os.walk(temp_path):
                if 'skill.py' in files:
                    skill_file = Path(root) / 'skill.py'
                    skill_folder_name = Path(root).name

                    try:
                        self._load_skill_file(skill_file, skill_folder_name)
                    except Exception as e:
                        log.error(f"执行插件技能模块失败 {skill_folder_name}: {e}")
                        raise
                    break

    def _load_skill_with_manifest(self, temp_path: Path, manifest_file: Path, zip_name: str):
        """使用 manifest.json 加载技能。"""
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"manifest.json 格式错误: {e}")

        # 验证 manifest 结构
        if 'main' not in manifest:
            raise ValueError("manifest.json 缺少 'main' 字段")

        main_config = manifest['main']
        entry_point = main_config.get('entry_point', 'skill/skill.py')

        # 定位 skill.py 文件
        skill_file = temp_path / entry_point
        if not skill_file.exists():
            raise ValueError(f"入口文件不存在: {entry_point}")

        # 从 manifest 中获取技能信息
        skill_info_manifest = manifest.get('skill_info', {})
        skill_name = skill_info_manifest.get('name', Path(zip_name).stem)
        skill_version = skill_info_manifest.get('version', '1.0.0')

        # 加载技能文件
        self._load_skill_file(skill_file, skill_name, skill_version, skill_info_manifest)

    def _load_skill_file(self, skill_file: Path, skill_name: str, skill_version: str = '1.0.0', skill_info_from_manifest: dict = None):
        spec = importlib.util.spec_from_file_location(
            f"plugins.{skill_name}.skill",
            skill_file
        )
        if spec is None or spec.loader is None:
            log.warning(f"无法创建模块规范: {skill_name}")
            return

        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as e:
            log.error(f"执行插件技能模块失败 {skill_name}: {e}")
            raise

        # 优先使用从 manifest 加载的技能信息
        if skill_info_from_manifest:
            skill_info = skill_info_from_manifest
            log.info(f"从 manifest.json 加载技能信息: {skill_name}")
        elif hasattr(module, 'skill_info'):
            skill_info = module.skill_info
            log.info(f"从模块加载技能信息: {skill_name}")
        else:
            log.warning(f"插件技能 {skill_name} 没有 skill_info 定义")
            return

        if 'name' not in skill_info:
            skill_info['name'] = skill_name

        # 添加版本信息
        if 'version' not in skill_info:
            skill_info['version'] = skill_version

        if 'functions' in skill_info:
            for func_name, func_info in skill_info['functions'].items():
                if hasattr(module, func_name):
                    func_info['callable'] = getattr(module, func_name)
                else:
                    log.warning(f"插件技能 {skill_info['name']} 的函数 {func_name} 未找到")

        self.skills[skill_info['name']] = skill_info
        log.info(f"插件技能加载成功: {skill_info['name']} (版本: {skill_info['version']})")

    def _resolve_skill_name(self, tool_name: str) -> Optional[tuple]:
        """从工具名解析出 (skill_name, func_name)，支持 "plugin-" 前缀。"""
        prefix = self._tool_prefix()
        if not tool_name.startswith(prefix):
            return None

        rest = tool_name[len(prefix):]
        parts = rest.split("_")
        if len(parts) < 2:
            return None

        for i in range(1, len(parts) + 1):
            possible_skill = "_".join(parts[:i])
            # 检查是否有 "plugin-" 前缀
            if possible_skill.startswith("plugin-"):
                possible_skill = possible_skill[7:]
            if possible_skill in self.skills:
                func_name = "_".join(parts[i:])
                return possible_skill, func_name
        return None

    def list_skills(self) -> list:
        from modules.main_server import config
        plugins_config = config.load_config().get('plugins', {})
        return [
            {
                "name": f"plugin-{skill_name}",
                "description": skill_info.get('description', ''),
                "version": skill_info.get('version', '1.0.0'),
                "functions": list(skill_info.get('functions', {}).keys()),
                "enabled": plugins_config.get(skill_name, True)
            }
            for skill_name, skill_info in self.skills.items()
        ]

    def toggle_skill(self, skill_name: str, enabled: bool) -> Dict[str, Any]:
        from modules.main_server import config

        # 移除 "plugin-" 前缀
        if skill_name.startswith("plugin-"):
            original_skill_name = skill_name[7:]
        else:
            original_skill_name = skill_name

        if original_skill_name not in self.skills:
            return {"error": f"插件技能不存在: {skill_name}"}

        current_config = config.load_config()
        if 'plugins' not in current_config:
            current_config['plugins'] = {}

        current_config['plugins'][original_skill_name] = enabled
        config.save_config(current_config)

        return {
            "success": True,
            "skill": skill_name,
            "enabled": enabled,
            "message": f"插件技能 '{skill_name}' 已{'启用' if enabled else '禁用'}"
        }


_plugin_skill_loader = None


def get_plugin_skill_loader() -> PluginSkillLoader:
    global _plugin_skill_loader
    if _plugin_skill_loader is None:
        _plugin_skill_loader = PluginSkillLoader()
    return _plugin_skill_loader
