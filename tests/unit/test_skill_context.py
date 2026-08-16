"""SkillContext 纯逻辑单元测试。

覆盖 resolve_path / is_path_allowed / filter_allowed_paths / require_confirmation /
require_user_input / file_operation / 日志与常量访问，
不触网、不依赖真实 request_manager / powershell_manager。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_skill_context -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.loader.skill_context import SkillContext, create_default_context


class FakeRequestManager:
    """模拟 request_manager 的确认/输入/文件操作接口。"""

    def __init__(self):
        self.confirmation_kwargs = None
        self.file_ops = []

    def create_skill_confirmation(self, message=None, action=None, **kwargs):
        self.confirmation_kwargs = {"message": message, "action": action, **kwargs}
        return {"requires_confirmation": True, "message": message, "action": action}

    def create_user_input_request(self, prompt=None, default_value=None):
        return {"prompt": prompt, "default_value": default_value}

    def create_file_operation_request(self, operation, **kwargs):
        return {"operation": operation, **kwargs}

    def handle_request(self, req, _):
        self.file_ops.append(req)
        return {"success": True, "operation": req["operation"]}


class FakePowershellManager:
    """模拟 powershell_manager 的脚本执行接口。"""

    async def execute_script(self, script, timeout, wait_time):
        return {"success": True, "script": script}

    async def check_script(self, command_id, wait_time):
        return {"success": True, "command_id": command_id}

    def kill_command(self, command_id):
        return {"success": True, "command_id": command_id}


class TestResolvePath(unittest.TestCase):
    """验证 resolve_path 的绝对/相对路径解析。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ctx = SkillContext(work_directory=self.tmp)

    def test_relative_path_resolved_against_work_dir(self):
        result = self.ctx.resolve_path("sub/file.txt")
        self.assertEqual(result, str((Path(self.tmp) / "sub/file.txt").resolve()))

    def test_absolute_path_resolved_as_is(self):
        abs_path = os.path.join(self.tmp, "a.txt")
        Path(abs_path).touch()
        result = self.ctx.resolve_path(abs_path)
        self.assertEqual(result, str(Path(abs_path).resolve()))

    def test_work_directory_property(self):
        self.assertEqual(self.ctx.work_directory, self.tmp)


class TestPathAllowed(unittest.TestCase):
    """验证 is_path_allowed 与 filter_allowed_paths。"""

    def test_default_allowed_when_no_checker(self):
        ctx = SkillContext(work_directory=".")
        result = ctx.is_path_allowed("any/path")
        self.assertEqual(result, {"allowed": True, "path": "any/path"})

    def test_uses_custom_checker(self):
        def checker(path):
            return {"allowed": path == "ok.txt", "path": path}

        ctx = SkillContext(work_directory=".", check_path_allowed=checker)
        self.assertTrue(ctx.is_path_allowed("ok.txt")["allowed"])
        self.assertFalse(ctx.is_path_allowed("bad.txt")["allowed"])

    def test_filter_allowed_paths_splits(self):
        def checker(path):
            return {"allowed": path != "blocked.txt", "path": path}

        ctx = SkillContext(work_directory=".", check_path_allowed=checker)
        allowed, blocked = ctx.filter_allowed_paths(["a.txt", "blocked.txt", "b.txt"])
        self.assertEqual(allowed, ["a.txt", "b.txt"])
        self.assertEqual(blocked, ["blocked.txt"])


class TestUserInteraction(unittest.TestCase):
    """验证 require_confirmation / require_user_input / file_operation。"""

    def setUp(self):
        self.rm = FakeRequestManager()
        self.ctx = SkillContext(work_directory=".", request_manager=self.rm)

    def test_require_confirmation_forwards(self):
        result = self.ctx.require_confirmation("执行?", "run_script", script="echo 1")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(self.rm.confirmation_kwargs["action"], "run_script")

    def test_require_confirmation_default_without_manager(self):
        ctx = SkillContext(work_directory=".")
        result = ctx.require_confirmation("执行?", "run_script")
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["action"], "run_script")

    def test_require_user_input_forwards(self):
        result = self.ctx.require_user_input("请输入路径", "default")
        self.assertEqual(result, {"prompt": "请输入路径", "default_value": "default"})

    def test_require_user_input_default_without_manager(self):
        ctx = SkillContext(work_directory=".")
        result = ctx.require_user_input("请输入路径")
        self.assertEqual(result, {"prompt": "请输入路径", "default_value": None})

    def test_file_operation_uses_work_directory_default(self):
        result = self.ctx.file_operation("create_file", file_path="a.txt", content="x")
        self.assertTrue(result["success"])
        self.assertEqual(self.rm.file_ops[0]["work_directory"], ".")

    def test_file_operation_error_without_manager(self):
        ctx = SkillContext(work_directory=".")
        result = ctx.file_operation("create_file", file_path="a.txt")
        self.assertIn("error", result)


class TestPowershell(unittest.TestCase):
    """验证 powershell 相关接口转发与降级。"""

    def setUp(self):
        self.ps = FakePowershellManager()
        self.ctx = SkillContext(work_directory=".", powershell_manager=self.ps)

    def test_execute_script_forwards(self):
        import asyncio
        result = asyncio.run(self.ctx.execute_script("echo hi"))
        self.assertTrue(result["success"])
        self.assertEqual(result["script"], "echo hi")

    def test_execute_script_error_without_manager(self):
        import asyncio
        ctx = SkillContext(work_directory=".")
        result = asyncio.run(ctx.execute_script("echo hi"))
        self.assertIn("error", result)

    def test_kill_command_error_without_manager(self):
        ctx = SkillContext(work_directory=".")
        result = ctx.kill_command("cmd-1")
        self.assertIn("error", result)


class TestLoggingAndConstants(unittest.TestCase):
    """验证日志转发与常量访问。"""

    def test_log_calls_forwarded(self):
        calls = []
        class FakeLogger:
            def info(self, m): calls.append(("info", m))
            def warning(self, m): calls.append(("warning", m))
            def error(self, m): calls.append(("error", m))

        logger = FakeLogger()
        ctx = SkillContext(work_directory=".", logger=logger)
        ctx.log_info("i")
        ctx.log_warning("w")
        ctx.log_error("e")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "info")

    def test_log_noop_without_logger(self):
        ctx = SkillContext(work_directory=".")
        ctx.log_info("i")  # 不应抛异常

    def test_constants_exposed(self):
        ctx = SkillContext(work_directory=".")
        self.assertTrue(hasattr(ctx.constants, "WARN_THRESHOLD"))
        self.assertTrue(hasattr(ctx.constants, "STREAM_MAX_HARD_LIMIT"))


class TestCreateDefaultContext(unittest.TestCase):
    """验证 create_default_context 工厂。"""

    def test_returns_context_with_work_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = create_default_context(tmp)
            self.assertIsInstance(ctx, SkillContext)
            self.assertEqual(ctx.work_directory, tmp)

    def test_default_checker_blocks_outside_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = create_default_context(tmp)
            result = ctx.is_path_allowed(str(Path(tmp).parent))
            self.assertFalse(result["allowed"])


if __name__ == "__main__":
    unittest.main()
