"""
Skill 执行上下文。
由 SkillManager 在调用 skill 函数时创建并注入，替代 skill 自行 import 内部模块。
"""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

from modules.bootstrap import constants


class SkillContext:
    """技能执行的统一上下文，封装所有 skill 需要的程序能力。"""

    def __init__(
        self,
        work_directory: str,
        logger=None,
        request_manager=None,
        backup_manager=None,
        powershell_manager=None,
        check_path_allowed: Optional[Callable] = None,
    ):
        self._work_directory = work_directory
        self._logger = logger
        self._request_manager = request_manager
        self._backup_manager = backup_manager
        self._powershell_manager = powershell_manager
        self._check_path_allowed = check_path_allowed

    # ===== 工作目录 =====
    @property
    def work_directory(self) -> str:
        return self._work_directory

    def resolve_path(self, file_path: str) -> str:
        """将相对路径解析为基于工作目录的绝对路径。"""
        p = Path(file_path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (Path(self._work_directory) / p).resolve()
        return str(resolved)

    # ===== 常量 =====
    @property
    def constants(self):
        """项目全局常量（只读），供技能读取文件大小、结果数量等限制类数值。"""
        return constants

    def is_path_allowed(self, file_path: str) -> Dict[str, Any]:
        """检查路径是否在工作目录内且未被 .dpc 限制（含逐级校验）。"""
        if self._check_path_allowed:
            return self._check_path_allowed(file_path)
        return {"allowed": True, "path": file_path}

    # ===== .dpc 限制 =====
    def get_restricted_paths(self) -> List[str]:
        """获取工作目录的 .dpc 屏蔽规则列表。"""
        from modules.chater import dpc_manager
        return dpc_manager.get_restricted_paths(self._work_directory)

    def filter_allowed_paths(self, paths: List[str]):
        """批量过滤路径，返回 (允许列表, 屏蔽列表)。"""
        allowed = []
        blocked = []
        for p in paths:
            if self.is_path_allowed(p).get("allowed"):
                allowed.append(p)
            else:
                blocked.append(p)
        return allowed, blocked

    def add_restriction(self, patterns: List[str]) -> None:
        """将文件/文件夹模式加入工作目录的 .dpc 屏蔽规则。"""
        from modules.chater import dpc_manager
        dpc_manager.ensure_restriction(self._work_directory, patterns)

    def remove_restriction(self, patterns: List[str]) -> None:
        """将文件/文件夹模式从工作目录的 .dpc 屏蔽规则中移除。"""
        from modules.chater import dpc_manager
        dpc_manager.remove_restriction(self._work_directory, patterns)

    # ===== 日志 =====
    @property
    def logger(self):
        return self._logger

    def log_info(self, msg: str):
        if self._logger:
            self._logger.info(msg)

    def log_warning(self, msg: str):
        if self._logger:
            self._logger.warning(msg)

    def log_error(self, msg: str):
        if self._logger:
            self._logger.error(msg)

    # ===== 用户交互（通过 request_manager）=====
    def require_confirmation(self, message: str, action: str, **kwargs) -> Dict[str, Any]:
        """请求用户确认操作。"""
        if self._request_manager:
            return self._request_manager.create_skill_confirmation(
                message=message, action=action, **kwargs
            )
        return {"requires_confirmation": True, "message": message, "action": action, **kwargs}

    def require_user_input(self, prompt: str, default_value: str = None) -> Dict[str, Any]:
        """请求用户输入。"""
        if self._request_manager:
            return self._request_manager.create_user_input_request(
                prompt=prompt, default_value=default_value
            )
        return {"prompt": prompt, "default_value": default_value}

    # ===== 文件操作（通过 request_manager 转发）=====
    def file_operation(self, operation: str, **kwargs) -> Dict[str, Any]:
        """通过 request_manager 执行文件操作。"""
        if not self._request_manager:
            return {"error": "request_manager 不可用"}
        kwargs.setdefault("work_directory", self._work_directory)
        req = self._request_manager.create_file_operation_request(operation, **kwargs)
        return self._request_manager.handle_request(req)

    # ===== 备份管理 =====
    @property
    def backup_manager(self):
        return self._backup_manager

    # ===== PowerShell 执行 =====
    @property
    def powershell_manager(self):
        return self._powershell_manager

    async def execute_script(self, script: str, timeout: int = 30, wait_time: int = 10) -> Dict[str, Any]:
        """执行 PowerShell 脚本。"""
        if self._powershell_manager:
            return await self._powershell_manager.execute_script(script, timeout, wait_time)
        return {"error": "powershell_manager 不可用"}

    async def check_script(self, command_id: str, wait_time: int = 10) -> Dict[str, Any]:
        if self._powershell_manager:
            return await self._powershell_manager.check_script(command_id, wait_time)
        return {"error": "powershell_manager 不可用"}

    def kill_command(self, command_id: str) -> Dict[str, Any]:
        if self._powershell_manager:
            return self._powershell_manager.kill_command(command_id)
        return {"error": "powershell_manager 不可用"}


def create_default_context(work_directory: str) -> SkillContext:
    """创建包含默认依赖的 SkillContext。"""
    logger = None
    request_manager = None
    backup_mgr = None
    ps_mgr = None

    try:
        from modules.main_server.middleware import request_manager as rm_mod
        request_manager = rm_mod.get_request_manager()
    except Exception as e:
        logging.getLogger("Dolphin.skill_context").warning(f"加载 request_manager 失败: {e}")

    try:
        from modules.functions import backup_manager as bm_mod
        backup_mgr = bm_mod.get_backup_manager()
    except Exception as e:
        logging.getLogger("Dolphin.skill_context").warning(f"加载 backup_manager 失败: {e}")

    try:
        from modules.functions import powershell_manager as ps_mod
        ps_mgr = ps_mod
    except Exception as e:
        logging.getLogger("Dolphin.skill_context").warning(f"加载 powershell_manager 失败: {e}")

    try:
        from modules.logger import get_logger
        logger = get_logger("Dolphin.skill_context")
    except Exception as e:
        logging.getLogger("Dolphin.skill_context").warning(f"加载 logger 失败: {e}")

    def _check_path(file_path: str) -> Dict[str, Any]:
        try:
            from modules.chater import dpc_manager
            work_path = Path(work_directory).resolve()
            p = Path(file_path)
            resolved = p.resolve() if p.is_absolute() else (work_path / p).resolve()
            try:
                resolved.relative_to(work_path)
            except ValueError:
                return {"allowed": False, "path": str(resolved), "message": f"路径不在工作目录内"}
            allowed, msg = dpc_manager.is_path_allowed_walkup(work_directory, str(resolved))
            return {"allowed": allowed, "path": str(resolved), "message": msg}
        except Exception as e:
            return {"allowed": False, "path": file_path, "error": str(e)}

    return SkillContext(
        work_directory=work_directory,
        logger=logger,
        request_manager=request_manager,
        backup_manager=backup_mgr,
        powershell_manager=ps_mgr,
        check_path_allowed=_check_path,
    )
