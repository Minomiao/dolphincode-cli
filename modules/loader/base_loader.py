"""
技能加载器基类。
提供 SkillManager 和 PluginSkillLoader 共用的工具注册、参数校验、调用分发等通用逻辑。
"""
import inspect
import asyncio
import traceback
from typing import Dict, List, Any, Optional

from modules.logger import get_logger
from modules.bootstrap import constants

log = get_logger("Dolphin.base_loader")


class BaseSkillLoader:
    """技能加载器基类。

    子类需实现：
        - _tool_prefix(): 工具名前缀，如 "skill_" 或 "plugin_"
        - _config_section(): 配置中启用/禁用的键名，如 "skills" 或 "plugins"
        - _load_skills(): 加载技能并填充 self.skills / self.failed_skills
    """

    def __init__(self):
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.failed_skills: Dict[str, str] = {}
        self._current_work_dir: Optional[str] = None
        # 完整工具名 → (skill_name, func_name)，加载时确定，调用时零歧义查表
        self._tool_lookup: Dict[str, tuple] = {}
        # 原生（内置）工具：{短名: {description, parameters, callable}}
        # 与目录技能共用前缀与查找表，注册名 = f"{前缀}{短名}"（无函数段）
        self.native_tools: Dict[str, Dict[str, Any]] = {}

    # ===== 子类必须实现的抽象接口 =====

    def _tool_prefix(self) -> str:
        """返回工具名前缀（如 "skill_" 或 "plugin_"）。"""
        raise NotImplementedError

    def _config_section(self) -> str:
        """返回配置中启用/禁用的键名（如 "skills" 或 "plugins"）。"""
        raise NotImplementedError

    def _load_skills(self):
        """加载技能并填充 self.skills / self.failed_skills。"""
        raise NotImplementedError

    # ===== 通用逻辑 =====

    def set_work_dir(self, work_dir: str):
        """设置当前工作目录，供 SkillContext 注入使用。"""
        self._current_work_dir = work_dir

    def _get_default_work_dir(self) -> str:
        try:
            from modules.main_server import config
            return config.load_config().get('work_directory', 'workplace')
        except Exception as e:
            log.warning(f"获取默认工作目录失败: {e}")
            return 'workplace'

    def _rebuild_tool_lookup(self):
        """从已加载技能生成完整工具名 → (skill_name, func_name) 精确映射表。

        加载时即确定全部注册名，调用时零歧义查表，不依赖运行时回溯；
        注册名冲突（技能名互为前缀且函数名巧合）以先注册者为准并告警。
        """
        lookup: Dict[str, tuple] = {}
        prefix = self._tool_prefix()
        for skill_name, skill_info in self.skills.items():
            for func_name, func_info in (skill_info.get('functions') or {}).items():
                if 'callable' not in func_info:
                    continue
                tool_name = f"{prefix}{skill_name}_{func_name}"
                if tool_name in lookup:
                    log.warning(
                        f"工具注册名冲突: {tool_name} 已归属技能 "
                        f"{lookup[tool_name][0]}，忽略来自 {skill_name} 的重复注册"
                    )
                    continue
                lookup[tool_name] = (skill_name, func_name)
        # 原生工具并入查找表：(短名, None) 表示原生条目；与技能重名时技能优先
        for name in self.native_tools:
            tool_name = f"{prefix}{name}"
            if tool_name in lookup:
                log.warning(
                    f"工具注册名冲突: {tool_name} 已被技能 "
                    f"{lookup[tool_name][0]} 占用，原生工具注册不生效"
                )
                continue
            lookup[tool_name] = (name, None)
        self._tool_lookup = lookup

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """返回当前启用技能的所有工具定义。"""
        from modules.main_server import config
        config_section = config.load_config().get(self._config_section(), {})

        tools = []
        for skill_name, skill_info in self.skills.items():
            if not config_section.get(skill_name, True):
                continue

            if 'functions' in skill_info:
                for func_name, func_info in skill_info['functions'].items():
                    if 'callable' in func_info:
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": f"{self._tool_prefix()}{skill_name}_{func_name}",
                                "description": func_info.get('description', ''),
                                "parameters": func_info.get('parameters', {
                                    "type": "object",
                                    "properties": {},
                                    "required": []
                                })
                            }
                        })

        # 原生（内置）工具：不参与启停配置，始终提供
        for name, info in self.native_tools.items():
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{self._tool_prefix()}{name}",
                    "description": info.get('description', ''),
                    "parameters": info.get('parameters', {
                        "type": "object",
                        "properties": {},
                        "required": []
                    })
                }
            })
        return tools

    def get_tool_names(self) -> List[str]:
        """返回所有工具名（不受启用状态过滤）。"""
        names = []
        for skill_name, skill_info in self.skills.items():
            if 'functions' in skill_info:
                for func_name in skill_info['functions'].keys():
                    names.append(f"{self._tool_prefix()}{skill_name}_{func_name}")
        names.extend(f"{self._tool_prefix()}{name}" for name in self.native_tools)
        return names

    def register_native_tool(self, name: str, description: str, parameters: dict, handler):
        """注册原生（内置）工具：无 skill.py 的代码级工具，与目录技能同一分发链。

        注册名 = f"{前缀}{name}"；同名重复注册以最后一次为准（支持实例重建）；
        与目录技能生成的注册名冲突时技能优先，本次注册不生效。

        Args:
            name: 工具短名（不含前缀）
            description: 工具描述（发给模型）
            parameters: JSON Schema 参数定义
            handler: 同步处理器，按参数名关键字调用，返回 dict 可携带
                user_output（终端标签）与 images（图片注入）字段

        Returns:
            True 注册成功 / False 因名称冲突被忽略
        """
        tool_name = f"{self._tool_prefix()}{name}"
        occupied = tool_name in self._tool_lookup and not any(
            f"{self._tool_prefix()}{n}" == tool_name for n in self.native_tools)
        if occupied:
            log.warning(f"原生工具 {tool_name} 与已注册工具冲突，注册被忽略")
            return False
        self.native_tools[name] = {
            "description": description,
            "parameters": parameters,
            "callable": handler,
        }
        self._rebuild_tool_lookup()
        log.info(f"原生工具注册成功: {tool_name}")
        return True

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用技能工具（按加载时确定的注册名精确查表）。"""
        log.info(f"调用技能工具: {tool_name}, 参数: {arguments}")
        resolved = self._tool_lookup.get(tool_name)
        if resolved is None:
            log.error(f"工具不存在或未注册: {tool_name}")
            raise ValueError(f"工具不存在: {tool_name}")

        skill_name, func_name = resolved
        if func_name is None:
            # 原生（内置）工具：直接取注册的处理器，条目结构与函数条目一致
            func_info = self.native_tools.get(skill_name)
        else:
            skill_info = self.skills[skill_name]
            if 'functions' not in skill_info or func_name not in skill_info['functions']:
                log.error(f"函数 {func_name} 在技能 {skill_name} 中不存在")
                raise ValueError(f"函数 {func_name} 在技能 {skill_name} 中不存在")
            func_info = skill_info['functions'][func_name]

        if not func_info or 'callable' not in func_info:
            log.error(f"工具 {tool_name} 不可调用")
            raise ValueError(f"工具 {tool_name} 不可调用")

        # 检查必需参数
        required_params = []
        if 'parameters' in func_info and 'required' in func_info['parameters']:
            required_params = func_info['parameters']['required']

        missing_params = [p for p in required_params if p not in arguments]
        if missing_params:
            error_msg = f"缺少必需参数: {', '.join(missing_params)}"
            log.error(f"技能工具执行失败: {tool_name}, {error_msg}")
            return {"error": error_msg, "missing_parameters": missing_params}

        func = func_info['callable']
        try:
            sig = inspect.signature(func)
            if 'context' in sig.parameters:
                from .skill_context import create_default_context
                ctx = create_default_context(self._current_work_dir or self._get_default_work_dir())
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, context=ctx, **arguments),
                    timeout=constants.SKILL_TIMEOUT)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(func, **arguments),
                    timeout=constants.SKILL_TIMEOUT)

            if asyncio.iscoroutine(result):
                result = await result

            log.debug(f"技能工具执行结果: {result}")
            return result
        except asyncio.TimeoutError:
            log.error(f"技能工具 {tool_name} 执行超时 ({constants.SKILL_TIMEOUT}s)")
            return {"error": f"工具执行超时 ({constants.SKILL_TIMEOUT}s)"}
        except TypeError as e:
            log.error(f"技能工具 {tool_name} 参数类型错误: {e}\n{traceback.format_exc()}")
            return {"error": "参数类型错误，请检查调用参数格式"}
        except ValueError as e:
            log.error(f"技能工具 {tool_name} 参数值错误: {e}\n{traceback.format_exc()}")
            return {"error": "参数值错误，请检查调用参数"}
        except KeyError as e:
            log.error(f"技能工具 {tool_name} 缺少必需键: {e}\n{traceback.format_exc()}")
            return {"error": "缺少必需参数"}
        except ImportError as e:
            log.error(f"技能工具 {tool_name} 依赖加载失败: {e}\n{traceback.format_exc()}")
            return {"error": "工具所需依赖加载失败"}
        except Exception as e:
            log.error(f"技能工具执行失败: {tool_name}, 错误: {e}")
            log.debug(f"错误详情:\n{traceback.format_exc()}")
            return {"error": "工具执行过程中发生内部错误"}

    def list_failed_skills(self) -> Dict[str, str]:
        return self.failed_skills.copy()

    def reload_skills(self) -> Dict[str, Any]:
        """重新加载所有技能。"""
        self.skills.clear()
        self.failed_skills.clear()
        self._load_skills()
        return {
            "success": True,
            "loaded_count": len(self.skills),
            "failed_count": len(self.failed_skills),
            "failed_skills": list(self.failed_skills.keys())
        }
