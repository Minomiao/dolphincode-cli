"""form 表单与字段编辑组件单元测试。

只覆盖校验逻辑与非交互回退路径（逐行 input），不涉及真实终端按键。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_form -v
"""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.CLIserver import form
from modules.CLIserver import key_nav
from modules.CLIserver.state import state


class _CmdStub:
    """替代命令模块，只提供回退菜单需要的接口。"""

    def get_command_keyword(self, name):
        return "/back"

    def get_command(self, name):
        return "/back"


def context_window_validator(text):
    """与 settings._context_window_validator 等价的校验器。"""
    value = text.strip()
    if not value:
        return True, "", ""
    try:
        number = int(value)
    except ValueError:
        return False, "invalid", text
    if number <= 0:
        return False, "invalid", text
    return True, "", str(number)


class _FallbackCase(unittest.TestCase):
    """屏蔽终端输出，并把列表/表单切到非交互回退路径（编辑页始终用普通输入）。"""

    def setUp(self):
        self._cmd = state.cmd
        state.cmd = _CmdStub()
        self.addCleanup(self._restore_state)

        available = patch.object(form.console_input, "is_available", return_value=False)
        available.start()
        self.addCleanup(available.stop)

        console = patch.object(form, "_console")
        console.start()
        self.addCleanup(console.stop)

        # 回退菜单会清屏并直接打印，测试中一并屏蔽
        for target in ("clear_screen", "_console"):
            patcher = patch.object(key_nav, target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _restore_state(self):
        state.cmd = self._cmd


class TestTextInput(_FallbackCase):
    """单字段编辑页（顶部信息表 + 普通行输入）。"""

    def test_returns_typed_value(self):
        with patch("builtins.input", return_value="hello"):
            ok, value = form.text_input("Title", "Prompt: ")
        self.assertTrue(ok)
        self.assertEqual(value, "hello")

    def test_empty_keeps_original_value(self):
        with patch("builtins.input", return_value=""):
            ok, value = form.text_input("Title", "Prompt: ", value="keep-me")
        self.assertTrue(ok)
        self.assertEqual(value, "keep-me")

    def test_invalid_then_valid_reprompts(self):
        with patch("builtins.input", side_effect=["abc", "4096"]):
            ok, value = form.text_input("Title", "Prompt: ", validate=context_window_validator)
        self.assertTrue(ok)
        self.assertEqual(value, "4096")

    def test_validator_normalizes_value(self):
        with patch("builtins.input", return_value="  8192  "):
            ok, value = form.text_input("Title", "Prompt: ", validate=context_window_validator)
        self.assertTrue(ok)
        self.assertEqual(value, "8192")

    def test_required_field_reprompts_when_empty(self):
        def required(text):
            value = text.strip()
            if not value:
                return False, "required", text
            return True, "", value

        with patch("builtins.input", side_effect=["", "my-model"]):
            ok, value = form.text_input("Title", "Prompt: ", required=True, validate=required)
        self.assertTrue(ok)
        self.assertEqual(value, "my-model")

    def test_interrupt_cancels_and_keeps_value(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt), \
                patch("builtins.print"):
            ok, value = form.text_input("Title", "Prompt: ", value="keep-me")
        self.assertFalse(ok)
        self.assertEqual(value, "keep-me")


class TestFormNavFallback(_FallbackCase):
    """字段表单的非交互回退。"""

    @staticmethod
    def _fields():
        return [
            {"key": "name", "label": "Name", "prompt": "Name: ", "value": "",
             "required": True, "required_message": "name required"},
            {"key": "description", "label": "Description", "prompt": "Description: ", "value": ""},
            {"key": "context_window", "label": "Context", "prompt": "Context: ", "value": "",
             "validate": context_window_validator},
        ]

    def test_collects_all_fields(self):
        with patch("builtins.input", side_effect=["gpt-4o", "", "64000"]):
            values = form.form_nav("Title", "Subtitle", self._fields(), submit_label="Submit")
        self.assertEqual(values["name"], "gpt-4o")
        self.assertEqual(values["description"], "")
        self.assertEqual(values["context_window"], "64000")

    def test_required_field_reprompts_when_empty(self):
        fields = self._fields()[:1]
        with patch("builtins.input", side_effect=["", "  ", "my-model"]):
            values = form.form_nav("Title", "Subtitle", fields, submit_label="Submit")
        self.assertEqual(values["name"], "my-model")

    def test_invalid_context_reprompts(self):
        fields = self._fields()[2:]
        with patch("builtins.input", side_effect=["nope", "2048"]):
            values = form.form_nav("Title", "Subtitle", fields, submit_label="Submit")
        self.assertEqual(values["context_window"], "2048")

    def test_missing_key_returns_empty_string(self):
        fields = [{"key": "description", "label": "Description", "prompt": "D: ", "value": ""}]
        with patch("builtins.input", return_value=""):
            values = form.form_nav("Title", "Subtitle", fields, submit_label="Submit")
        self.assertEqual(values, {"description": ""})


class TestConfirmNavFallback(_FallbackCase):
    """确认页的非交互回退（数字菜单）。"""

    def test_first_option_confirms(self):
        with patch("builtins.input", return_value="1"):
            self.assertTrue(form.confirm_nav("Title", "Message", "Yes", "No"))

    def test_second_option_cancels(self):
        with patch("builtins.input", return_value="2"):
            self.assertFalse(form.confirm_nav("Title", "Message", "Yes", "No"))


if __name__ == "__main__":
    unittest.main()
