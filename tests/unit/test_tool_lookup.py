"""技能工具注册查表机制单元测试。

验证 _tool_lookup 加载时确定注册名、调用时零歧义查表：
- 技能名互为前缀且函数名巧合时不再错路由（冲突以先注册者为准）
- 未注册工具名报 ValueError
- mcp_manager 统一 mcp_ 前缀注册与非法字符清洗

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_tool_lookup -v
"""
import asyncio
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.loader.base_loader import BaseSkillLoader
from modules.loader.skill_manager import SkillManager
from modules.loader.mcp_manager import MCPManager


def _bare_skill_loader(prefix: str = "skill_") -> SkillManager:
    """构造仅含查表机制的 SkillManager（绕过目录加载）。"""
    loader = SkillManager.__new__(SkillManager)
    BaseSkillLoader.__init__(loader)
    loader._tool_prefix = lambda: prefix
    return loader


def _skill(name: str, func_name: str, func):
    """构造单函数技能的 skill_info。"""
    return {
        "name": name,
        "functions": {
            func_name: {"description": "", "parameters": {}, "callable": func}
        },
    }


class TestToolLookup(unittest.TestCase):
    """_tool_lookup 查表机制。"""

    def test_exact_resolution(self):
        """完整工具名精确映射到 (skill, func)。"""
        loader = _bare_skill_loader()
        loader.skills = {
            "calc": _skill("calc", "run", lambda a: a),
            "calc_ext": _skill("calc_ext", "run", lambda a: a),
        }
        loader._rebuild_tool_lookup()

        self.assertEqual(loader._tool_lookup["skill_calc_run"], ("calc", "run"))
        self.assertEqual(loader._tool_lookup["skill_calc_ext_run"], ("calc_ext", "run"))

    def test_prefix_overlap_conflict_first_wins(self):
        """注册名冲突（技能互为前缀且函数名巧合）：先注册者胜出并告警。"""
        loader = _bare_skill_loader()
        loader.skills = {
            "calc": _skill("calc", "ext_run", lambda: "a"),
            "calc_ext": _skill("calc_ext", "run", lambda: "b"),
        }
        loader._rebuild_tool_lookup()

        # 两者都会生成 skill_calc_ext_run，先注册的 calc 胜出
        self.assertEqual(loader._tool_lookup["skill_calc_ext_run"], ("calc", "ext_run"))
        self.assertEqual(len(loader._tool_lookup), 1)

    def test_unregistered_tool_raises(self):
        """未注册工具名查表未命中 → ValueError。"""
        loader = _bare_skill_loader()
        loader.skills = {"demo": _skill("demo", "run", lambda: 1)}
        loader._rebuild_tool_lookup()

        with self.assertRaises(ValueError):
            asyncio.run(loader.call_tool("skill_demo_missing", {}))

    def test_call_tool_dispatches_via_lookup(self):
        """call_tool 按查表结果执行目标函数。"""
        loader = _bare_skill_loader()
        loader.skills = {"calc": _skill("calc", "run", lambda x: {"double": x * 2})}
        loader._rebuild_tool_lookup()

        result = asyncio.run(loader.call_tool("skill_calc_run", {"x": 21}))
        self.assertEqual(result, {"double": 42})

    def test_reload_rebuilds_lookup(self):
        """reload_skills 后查表随 skills 重建。"""
        loader = _bare_skill_loader()
        loader.skills = {"old": _skill("old", "run", lambda: 1)}
        loader._rebuild_tool_lookup()

        loader.skills.clear()
        loader.skills = {"new": _skill("new", "run", lambda: 1)}
        loader.reload_skills = None  # reload 会清空 skills，此处仅验证 rebuild 联动
        loader._rebuild_tool_lookup()

        self.assertNotIn("skill_old_run", loader._tool_lookup)
        self.assertIn("skill_new_run", loader._tool_lookup)


class TestMCPRegistration(unittest.IsolatedAsyncioTestCase):
    """mcp_manager 统一 mcp_ 前缀注册。"""

    def test_register_normalizes_and_prefixes(self):
        """非法字符清洗 + mcp_ 前缀，get_all_tools 暴露注册名。"""
        mgr = MCPManager()
        mgr.register_server_tools("fs.server", [
            {"name": "read.file", "description": "读文件", "input_schema": None},
        ])

        tools = mgr.get_all_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "mcp_fs_server_read_file")
        # schema 缺省补全
        self.assertEqual(tools[0]["function"]["parameters"],
                         {"type": "object", "properties": {}, "required": []})

    async def test_call_tool_maps_back_to_server_and_raw_name(self):
        """call_tool 查表反解 (server, 原始工具名)，未连接时报错。"""
        mgr = MCPManager()
        mgr.register_server_tools("fs", [{"name": "read_file"}])

        with self.assertRaises(ValueError) as ctx:
            await mgr.call_tool("mcp_fs_read_file", {})
        self.assertIn("未连接", str(ctx.exception))

    async def test_call_tool_unregistered_raises(self):
        """未注册的 mcp_ 名报未注册错误。"""
        mgr = MCPManager()
        with self.assertRaises(ValueError) as ctx:
            await mgr.call_tool("mcp_ghost_tool", {})
        self.assertIn("未注册", str(ctx.exception))

    def test_duplicate_registration_raises(self):
        """注册名冲突在注册时报错。"""
        mgr = MCPManager()
        tool = [{"name": "run"}]
        mgr.register_server_tools("fs", tool)
        with self.assertRaises(ValueError):
            mgr.register_server_tools("fs", tool)


class TestNativeTool(unittest.TestCase):
    """原生（内置）工具注册接口。"""

    def test_register_and_lookup_and_call(self):
        """注册后进入查找表与工具列表，call_tool 走原生分支并透传参数。"""
        loader = _bare_skill_loader()
        seen = []

        def handler(value=""):
            seen.append(value)
            return {"success": True, "value": value,
                    "user_output": {"label": "X", "parts": [{"text": "ok"}]}}

        self.assertTrue(loader.register_native_tool(
            "echo", description="测试工具",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=handler))
        self.assertEqual(loader._tool_lookup["skill_echo"], ("echo", None))
        self.assertIn("skill_echo", loader.get_tool_names())
        self.assertIn("skill_echo",
                      [t["function"]["name"] for t in loader.get_all_tools()])

        result = asyncio.run(loader.call_tool("skill_echo", {"value": "hi"}))
        self.assertTrue(result["success"])
        self.assertEqual(seen, ["hi"])
        # user_output 原样保留，由 chat._execute_tool 的通用提取逻辑处理
        self.assertIn("user_output", result)

    def test_reregister_overwrites(self):
        """同名重复注册以最后一次为准（支持 chat 实例重建）。"""
        loader = _bare_skill_loader()
        loader.register_native_tool("t", "旧", {}, lambda: "old")
        loader.register_native_tool("t", "新", {}, lambda: "new")
        self.assertEqual(loader._tool_lookup["skill_t"], ("t", None))
        self.assertEqual(loader.get_all_tools()[0]["function"]["description"], "新")

    def test_conflict_with_directory_skill(self):
        """与目录技能生成的注册名冲突时技能优先，原生注册返回 False。"""
        loader = _bare_skill_loader()
        loader.skills = {"echo": _skill("echo", "run", lambda: None)}
        loader._rebuild_tool_lookup()
        ok = loader.register_native_tool(
            "echo_run", description="冲突", parameters={}, handler=lambda: None)
        self.assertFalse(ok)
        self.assertEqual(loader._tool_lookup["skill_echo_run"], ("echo", "run"))

    def test_missing_callable_raises(self):
        """原生条目处理器丢失时报 ValueError 而非静默失败。"""
        loader = _bare_skill_loader()
        loader.register_native_tool("t", "d", {}, lambda: None)
        del loader.native_tools["t"]
        with self.assertRaises(ValueError):
            asyncio.run(loader.call_tool("skill_t", {}))


if __name__ == "__main__":
    unittest.main()
