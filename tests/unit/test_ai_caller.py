"""ai_caller 单元测试：白名单匹配、_build_result 结构、chat_ai 完整流程。

合并自原 tests/test_ai_caller.py（同目录遗留）并适配查表白名单新签名。
"""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater.context import ContextManager
from modules.functions import ai_caller


# ===== 桩与夹具 =====

def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def _stub_chat():
    """构造带三方加载器查表的 chat 桩。"""
    return SimpleNamespace(
        skill_mgr=SimpleNamespace(_tool_lookup={
            "skill_file_manager_list_dir": ("file_manager", "list_dir"),
            "skill_file_manager_read": ("file_manager", "read"),
            "skill_calculator_run": ("calculator", "run"),
        }),
        plugin_loader=SimpleNamespace(_tool_lookup={
            "plugin_user_input_request_user_input": ("user_input", "request_user_input"),
        }),
        std_loader=SimpleNamespace(_tool_lookup={
            "stdskill_git": ("git", "run"),
            "stdskill_taste-skill": ("taste-skill", "run"),
        }),
    )


def make_messages():
    """构造包含思考过程、工具调用、工具结果的完整消息历史。"""
    return [
        {"role": "user", "content": "列出当前目录文件", "_context": "工作目录: workspace"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "我需要先查看目录结构",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "skill_file_manager_list_directory",
                        "arguments": '{"path": "."}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"success": true, "files": ["a.txt", "b.md"]}'},
        {"role": "assistant", "content": "当前目录包含 a.txt 和 b.md。"},
    ]


class FakeChat:
    """模拟 DolphinChat 实例，仅承载消息历史与上下文统计，不触网。"""

    def __init__(self, messages, context=None):
        self.messages = messages
        self.context = context or ContextManager(lambda: "系统提示", None)
        self.model = "deepseek-v4-flash"


class FakeDolphinChat:
    """替换真实 DolphinChat：不触网，chat() 注入模拟消息历史并返回固定文本。"""

    def __init__(self, model=None, temperature=0.7, max_tokens=None, enable_tools=True, callback=None):
        self.model = model or "deepseek-v4-flash"
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.enable_tools = enable_tools
        self.callback = callback
        self.tools = [] if not enable_tools else [
            _tool("skill_file_manager_list_directory"),
        ]
        # 热加载白名单需要加载器查表
        self.skill_mgr = SimpleNamespace(_tool_lookup={
            "skill_file_manager_list_directory": ("file_manager", "list_directory"),
        })
        self.plugin_loader = SimpleNamespace(_tool_lookup={})
        self.std_loader = SimpleNamespace(_tool_lookup={})
        self.current_work_directory = "workplace"
        self.default_work_directory = "workplace"
        self.effort_level = "fine"
        self.messages = []
        self.context = ContextManager(lambda: "系统提示", None)

    def get_system_prompt(self) -> str:
        return "你是一个AI助手。"

    async def chat(self, user_input, max_tool_rounds=10):
        self.messages = make_messages()
        return "当前目录包含 a.txt 和 b.md。"


EXPECTED_KEYS = {"content", "reasoning", "tool_calls", "messages", "usage", "truncated", "rounds"}


# ===== 白名单三级匹配 =====

class TestToolAllowed(unittest.TestCase):
    """白名单三级匹配：完整名 / 技能名 / 函数名。"""

    def setUp(self):
        self.chat = _stub_chat()
        self.ids = ai_caller._tool_ids(self.chat)

    def test_skill_name_enables_all_functions(self):
        """传技能名放行该技能全部函数（旧后缀匹配的核心缺陷场景）。"""
        tool = _tool("skill_file_manager_list_dir")
        self.assertTrue(ai_caller._tool_allowed(tool, ["file_manager"], self.ids))

    def test_full_tool_name(self):
        tool = _tool("stdskill_git")
        self.assertTrue(ai_caller._tool_allowed(tool, ["stdskill_git"], self.ids))

    def test_function_name(self):
        tool = _tool("skill_file_manager_read")
        self.assertTrue(ai_caller._tool_allowed(tool, ["read"], self.ids))

    def test_std_pack_name(self):
        """合集 pack 名放行合集工具。"""
        tool = _tool("stdskill_taste-skill")
        self.assertTrue(ai_caller._tool_allowed(tool, ["taste-skill"], self.ids))

    def test_unrelated_allowed_list_rejects(self):
        tool = _tool("skill_calculator_run")
        self.assertFalse(ai_caller._tool_allowed(tool, ["file_manager"], self.ids))

    def test_unregistered_name_rejects(self):
        tool = _tool("skill_ghost_run")
        self.assertFalse(ai_caller._tool_allowed(tool, ["file_manager"], self.ids))

    def test_ids_cover_all_registered_tools(self):
        """标识符表覆盖全部注册工具。"""
        self.assertEqual(len(self.ids), 6)


# ===== _build_result 结构 =====

class TestBuildResult(unittest.TestCase):
    """验证 _build_result 返回的 dict 结构。"""

    def test_full_structure(self):
        chat = FakeChat(make_messages())
        result = ai_caller._build_result(chat, "当前目录包含 a.txt 和 b.md。")

        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")
        self.assertEqual(result["reasoning"], ["我需要先查看目录结构"])
        self.assertEqual(len(result["tool_calls"]), 1)
        call = result["tool_calls"][0]
        self.assertEqual(call["name"], "skill_file_manager_list_directory")
        self.assertIn('"path"', call["arguments"])
        self.assertIn('"success": true', call["result"])
        self.assertEqual(len(result["messages"]), 4)
        self.assertNotIn("_context", result["messages"][0])
        for key in ("usage_ratio", "prompt_tokens", "completion_tokens", "turn_count"):
            self.assertIn(key, result["usage"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rounds"], 1)

    def test_truncated_when_last_assistant_still_calls_tools(self):
        messages = make_messages()
        messages[-1] = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "skill_file_manager_list_directory", "arguments": "{}"},
                }
            ],
        }
        chat = FakeChat(messages)
        result = ai_caller._build_result(chat, "")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["rounds"], 2)

    def test_internal_fields_stripped(self):
        """返回历史应剥离全部内部字段（_context / _send / _display / _images）。"""
        messages = make_messages()
        messages[0]["_send"] = False
        messages[-1]["_display"] = False
        messages[0]["_images"] = [{"path": "/tmp/a.png", "media_type": "image/png"}]
        chat = FakeChat(messages)
        result = ai_caller._build_result(chat, "ok")
        self.assertEqual(len(result["messages"]), 4)
        for msg in result["messages"]:
            for field in ("_context", "_send", "_display", "_images"):
                self.assertNotIn(field, msg)

    def test_empty_history(self):
        chat = FakeChat([])
        result = ai_caller._build_result(chat, "无输入")
        self.assertEqual(result["content"], "无输入")
        self.assertEqual(result["reasoning"], [])
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(result["messages"], [])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rounds"], 0)


# ===== chat_ai 完整流程 =====

class TestChatAiFlow(unittest.TestCase):
    """验证 chat_ai / chat_ai_sync 完整流程（mock DolphinChat，不触网）。"""

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_returns_full_dict(self):
        result = asyncio.run(ai_caller.chat_ai("列出当前目录文件"))
        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")
        self.assertEqual(len(result["tool_calls"]), 1)

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_sync_returns_full_dict(self):
        result = ai_caller.chat_ai_sync("列出当前目录文件")
        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_whitelist_keeps_matched_tool(self):
        """白名单按技能名命中：工具被保留（修复前被误裁剪为空）。"""
        result = asyncio.run(ai_caller.chat_ai("列出当前目录文件",
                                               allowed_tools=["file_manager"]))
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")
        self.assertEqual(len(result["tool_calls"]), 1)

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_whitelist_filters_unmatched(self):
        """白名单无命中：工具被裁剪为空。"""
        result = asyncio.run(ai_caller.chat_ai("列出当前目录文件",
                                               allowed_tools=["不存在的工具"]))
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_no_tools(self):
        result = asyncio.run(ai_caller.chat_ai("解释什么是闭包", enable_tools=False))
        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["rounds"], 1)


if __name__ == "__main__":
    unittest.main()
