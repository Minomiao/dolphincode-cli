"""ai_caller.chat_ai 返回完整 dict 结构的单元测试。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest discover -s tests -v
    venv\\Scripts\\python.exe tests\\test_ai_caller.py
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

# 将项目根目录加入导入路径，保证直接从脚本运行时也能找到 modules 包
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 模拟主程序启动：初始化路径（config.load_config、logger 等依赖 app_paths）
from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater.context import ContextManager
from modules.functions import ai_caller


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
            {
                "type": "function",
                "function": {
                    "name": "skill_file_manager_list_directory",
                    "description": "列出目录",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ]
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


class TestBuildResult(unittest.TestCase):
    """验证 _build_result 返回的 dict 结构。"""

    def test_full_structure(self):
        chat = FakeChat(make_messages())
        result = ai_caller._build_result(chat, "当前目录包含 a.txt 和 b.md。")

        # 顶层键齐全
        self.assertEqual(set(result), EXPECTED_KEYS)

        # content：最终回复文本
        self.assertIsInstance(result["content"], str)
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")

        # reasoning：各轮思考过程
        self.assertIsInstance(result["reasoning"], list)
        self.assertEqual(result["reasoning"], ["我需要先查看目录结构"])

        # tool_calls：工具名 / 参数 / 执行结果一一对应
        self.assertIsInstance(result["tool_calls"], list)
        self.assertEqual(len(result["tool_calls"]), 1)
        call = result["tool_calls"][0]
        self.assertEqual(call["name"], "skill_file_manager_list_directory")
        self.assertIn('"path"', call["arguments"])
        self.assertIn('"success": true', call["result"])

        # messages：完整历史，且内部 _context 字段已被清理
        self.assertIsInstance(result["messages"], list)
        self.assertEqual(len(result["messages"]), 4)
        self.assertNotIn("_context", result["messages"][0])

        # usage：用量统计
        self.assertIsInstance(result["usage"], dict)
        for key in ("usage_ratio", "prompt_tokens", "completion_tokens", "turn_count"):
            self.assertIn(key, result["usage"])

        # 正常结束：未截断，1 个工具回合
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rounds"], 1)

    def test_truncated_when_last_assistant_still_calls_tools(self):
        messages = make_messages()
        # 最后一条 assistant 仍带 tool_calls → 视为达到回合上限被截断
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

    def test_empty_history(self):
        chat = FakeChat([])
        result = ai_caller._build_result(chat, "无输入")
        self.assertEqual(result["content"], "无输入")
        self.assertEqual(result["reasoning"], [])
        self.assertEqual(result["tool_calls"], [])
        self.assertEqual(result["messages"], [])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["rounds"], 0)


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
    def test_chat_ai_tool_whitelist_filters_tools(self):
        """白名单过滤后 FakeDolphinChat.tools 应被裁剪为空。"""
        result = asyncio.run(ai_caller.chat_ai("列出当前目录文件", allowed_tools=["不存在的工具"]))
        self.assertEqual(result["content"], "当前目录包含 a.txt 和 b.md。")

    @patch("modules.chater.chat.DolphinChat", FakeDolphinChat)
    def test_chat_ai_no_tools(self):
        result = asyncio.run(ai_caller.chat_ai("解释什么是闭包", enable_tools=False))
        self.assertEqual(set(result), EXPECTED_KEYS)
        self.assertEqual(result["rounds"], 1)


if __name__ == "__main__":
    unittest.main()
