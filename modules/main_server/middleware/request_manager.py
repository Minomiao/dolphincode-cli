import asyncio
import concurrent.futures
from typing import Dict, Any, Optional, Awaitable
from modules.bootstrap import constants
from modules.logger import get_logger

log = get_logger("Dolphin.request_manager")


# 共享线程池：在运行中的事件循环内以独立线程执行协程。
# 复用单一执行器可保证超时后悬挂线程最多 1 个，不会随调用次数累积。
_sync_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def _run_async(coro: Awaitable, timeout: float = constants.API_TIMEOUT) -> Any:
    """在同步或异步上下文中安全执行协程。

    - 已在事件循环内运行时：将协程提交到独立线程的独立事件循环执行，
      避免跨线程使用主循环对象，并设置超时防止永久挂起
    - 无事件循环时：使用 asyncio.run() 创建新循环

    用于在同步请求处理函数中调用异步的 skill/工具接口，
    解决 Flask 同步路由与 async call_tool 之间的兼容问题。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        # 已有运行中的事件循环，避免 asyncio.run() 的 "cannot run in running loop" 错误
        if loop.is_running():
            # 创建 Task 并等待完成（适用于嵌套在已有 async 上下文中的同步调用）
            future = _sync_executor.submit(asyncio.run, coro)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                log.error(f"协程执行超过 {timeout}s 超时")
                raise TimeoutError(f"协程执行超时 ({timeout}s)")
        return loop.run_until_complete(coro)

class RequestType:
    """请求类型枚举"""
    USER_INPUT = "user_input_request"
    CONFIRMATION = "confirmation_request"
    SKILL_CONFIRMATION = "skill_confirmation"
    PROMPT_REQUEST = "prompt_request"
    FILE_OPERATION = "file_operation"

class RequestManager:
    """申请管理器"""
    def __init__(self) -> None:
        self._prompt_manager: Optional[Any] = None
        self._file_operation: Optional[Any] = None
        log.info("RequestManager 初始化完成")

    def _get_prompt_manager(self) -> Any:
        """延迟加载提示词管理器"""
        if self._prompt_manager is None:
            from modules.main_server import prompt_manager
            self._prompt_manager = prompt_manager.get_prompt_manager()
        return self._prompt_manager

    def _get_file_operation(self) -> Any:
        """延迟加载文件操作管理器"""
        if self._file_operation is None:
            from modules.functions import file_operation
            self._file_operation = file_operation.get_file_operation()
        return self._file_operation
    
    def create_user_input_request(self, prompt: str, input_type: str = "text", 
                               default_value: Optional[str] = None, 
                               validation_pattern: Optional[str] = None) -> Dict[str, Any]:
        """创建用户输入申请"""
        request = {
            "type": RequestType.USER_INPUT,
            "prompt": prompt,
            "input_type": input_type,
            "default_value": default_value,
            "validation_pattern": validation_pattern
        }
        log.debug(f"创建用户输入申请: {prompt}")
        return request

    def create_skill_confirmation(self, message: str, action: str, **kwargs) -> Dict[str, Any]:
        """创建技能确认申请"""
        request = {
            "type": RequestType.SKILL_CONFIRMATION,
            "requires_confirmation": True,
            "message": message,
            "action": action,
            **kwargs
        }
        log.debug(f"创建技能确认申请: {action}")
        return request

    def create_prompt_request(self, prompt_key: str, **kwargs) -> Dict[str, Any]:
        """创建提示词请求"""
        request = {
            "type": RequestType.PROMPT_REQUEST,
            "prompt_key": prompt_key,
            "kwargs": kwargs
        }
        log.debug(f"创建提示词请求: {prompt_key}")
        return request

    def create_file_operation_request(self, operation_type: str, **kwargs) -> Dict[str, Any]:
        """创建文件操作请求"""
        request = {
            "type": RequestType.FILE_OPERATION,
            "operation_type": operation_type,
            **kwargs
        }
        log.debug(f"创建文件操作请求: {operation_type}")
        return request
    
    def is_request(self, data: Any) -> bool:
        """判断是否为请求对象。"""
        if not isinstance(data, dict):
            return False

        # 已注册类型、技能确认标记或面向用户输出均视为请求
        if data.get("type") in [RequestType.USER_INPUT, RequestType.CONFIRMATION,
                                RequestType.PROMPT_REQUEST, RequestType.FILE_OPERATION]:
            return True
        if data.get("requires_confirmation"):
            return True
        if data.get("user_output"):
            return True
        return False

    def handle_request(self, request: Dict[str, Any]) -> Any:
        """处理请求：可执行类型派发到执行器，其余原样返回给主程序处理。"""
        if not self.is_request(request):
            return request

        if request.get("requires_confirmation"):
            log.info("技能确认申请，由主程序处理")
            return request

        request_type = request.get("type")
        if request_type == RequestType.USER_INPUT:
            log.info("用户输入申请，由主程序处理")
            return request
        if request_type == RequestType.CONFIRMATION:
            log.info("确认申请，由主程序处理")
            return request
        if request_type == RequestType.PROMPT_REQUEST:
            return self._handle_prompt_request(request)
        if request_type == RequestType.FILE_OPERATION:
            return self._handle_file_operation(request)
        return request

    def _handle_prompt_request(self, request: Dict[str, Any]) -> Any:
        """处理提示词请求"""
        try:
            prompt_key = request.get('prompt_key')
            prompt_manager = self._get_prompt_manager()
            result = prompt_manager.handle_request(request)
            log.info(f"处理提示词请求: {prompt_key}, 成功: {result.get('success', False)}")
            return result
        except Exception:
            log.exception("处理提示词请求失败")
            return {"error": "提示词请求处理失败"}

    def _handle_file_operation(self, request: Dict[str, Any]) -> Any:
        """处理文件操作请求"""
        try:
            operation_type = request.get('operation_type')
            file_operation = self._get_file_operation()
            result = file_operation.handle_request(request)
            log.info(f"处理文件操作请求: {operation_type}, 成功: {result.get('success', False)}")
            return result
        except Exception:
            log.exception("处理文件操作请求失败")
            return {"error": "文件操作请求处理失败"}


# 单例模式
_request_manager = None

# AI 临时工作目录（对话级别），None 表示未设置，此时使用 config.json 的值
_ai_work_directory = None

def get_request_manager() -> RequestManager:
    global _request_manager
    if _request_manager is None:
        _request_manager = RequestManager()
    return _request_manager

def set_ai_work_directory(work_dir: str) -> None:
    global _ai_work_directory
    _ai_work_directory = work_dir

def get_ai_work_directory() -> Optional[str]:
    global _ai_work_directory
    return _ai_work_directory

def reset_ai_work_directory() -> None:
    global _ai_work_directory
    _ai_work_directory = None

def get_persisted_work_directory() -> str:
    from modules.main_server import config
    return config.load_config().get('work_directory', 'workplace')
