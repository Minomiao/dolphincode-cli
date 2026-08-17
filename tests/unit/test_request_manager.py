"""request_manager #23 修复单元测试。

验证：
- _run_async 无运行 loop 时走 asyncio.run，有运行 loop 时复用共享线程池
- _run_async 超时抛出 TimeoutError，且共享池线程数受控（最多 1 个）
- handle_request 已移除 callback 死参数
- logger get 请求返回名称而非 Logger 对象（可 JSON 序列化）

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_request_manager -v
"""
import asyncio
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.main_server.middleware.request_manager import (
    RequestManager,
    RequestType,
    _run_async,
    _sync_executor,
)


class TestRunAsync(unittest.TestCase):
    """验证 _run_async 的三种执行路径。"""

    def test_without_running_loop(self):
        async def quick():
            return 42

        self.assertEqual(_run_async(quick()), 42)

    def test_with_running_loop_uses_shared_pool(self):
        async def outer():
            async def inner():
                return 7

            return _run_async(inner())

        self.assertEqual(asyncio.run(outer()), 7)

    def test_shared_pool_single_worker(self):
        # 共享池只允许 1 个工作线程，超时悬挂的线程不会随调用次数累积
        self.assertEqual(_sync_executor._max_workers, 1)

    def test_timeout_raises_timeout_error(self):
        async def outer():
            async def slow():
                await asyncio.sleep(0.3)
                return "done"

            return _run_async(slow(), timeout=0.05)

        with self.assertRaises(TimeoutError):
            asyncio.run(outer())


class TestHandleRequest(unittest.TestCase):
    """验证 handle_request 移除 callback 死参数后的行为。"""

    def setUp(self):
        self.mgr = RequestManager()

    def test_non_request_passthrough(self):
        data = {"foo": "bar"}
        self.assertEqual(self.mgr.handle_request(data), data)

    def test_user_input_request_passthrough(self):
        req = {"type": RequestType.USER_INPUT, "prompt": "hi"}
        self.assertEqual(self.mgr.handle_request(req), req)

    def test_logger_get_returns_name_not_object(self):
        result = self.mgr.handle_request({
            "type": RequestType.LOGGER_REQUEST,
            "operation_type": "get",
            "name": "Dolphin.test",
        })
        self.assertTrue(result["success"])
        self.assertEqual(result["name"], "Dolphin.test")
        self.assertNotIn("logger", result)


if __name__ == "__main__":
    unittest.main()
