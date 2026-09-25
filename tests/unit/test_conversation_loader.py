"""format_conversation_history 的显示过滤单元测试。

验证 _display=False 的消息不在历史回显中出现。
不触网、不依赖配置，仅使用 stdlib unittest。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_conversation_loader -v
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater.conversation_loader import format_conversation_history


class TestDisplayFilter(unittest.TestCase):
    """验证 _display=False 的消息不在历史回显中出现。"""

    def test_hidden_user_message_not_displayed(self):
        messages = [
            {"role": "user", "content": "隐藏的问题", "_display": False},
            {"role": "user", "content": "可见的问题"},
        ]
        text = format_conversation_history(messages, show_thinking=False)
        self.assertIn("可见的问题", text)
        self.assertNotIn("隐藏的问题", text)

    def test_hidden_assistant_message_not_displayed(self):
        messages = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "隐藏回答", "_display": False},
            {"role": "assistant", "content": "可见回答"},
        ]
        text = format_conversation_history(messages, show_thinking=False)
        self.assertIn("可见回答", text)
        self.assertNotIn("隐藏回答", text)

    def test_all_hidden_returns_empty_display(self):
        messages = [{"role": "user", "content": "隐藏", "_display": False}]
        text = format_conversation_history(messages, show_thinking=False)
        self.assertNotIn("隐藏", text)

    def test_messages_without_flag_displayed(self):
        messages = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        text = format_conversation_history(messages, show_thinking=False)
        self.assertIn("你好", text)
        self.assertIn("你好！", text)


if __name__ == "__main__":
    unittest.main()
