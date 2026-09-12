"""key_nav 列表导航组件的刷新行为单元测试。

重点覆盖 refresh_fn：列表被就地增删（如模型管理）时，
非交互回退菜单必须使用刷新后的选项，而不是进入界面时的快照。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_key_nav -v
"""
import io
import os
import sys
import unittest
from unittest.mock import patch

from rich.console import Console

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.CLIserver import key_nav
from modules.CLIserver.state import state


class _CmdStub:
    """替代命令模块，只提供回退菜单需要的接口。"""

    def get_command_keyword(self, name):
        return "/back"

    def get_command(self, name):
        return "/back"


class TestNumberMenuRefresh(unittest.TestCase):
    """非交互回退菜单的 refresh_fn 行为。"""

    def setUp(self):
        self._cmd = state.cmd
        state.cmd = _CmdStub()
        self.addCleanup(self._restore_state)

        available = patch.object(key_nav.console_input, "is_available", return_value=False)
        available.start()
        self.addCleanup(available.stop)

        for target in ("clear_screen", "_console"):
            patcher = patch.object(key_nav, target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _restore_state(self):
        state.cmd = self._cmd

    def test_menu_uses_refreshed_options(self):
        """初始快照只有 1 项，刷新后有 2 项，选 2 应命中新增项。"""
        selected = []

        def refresh():
            return {"options": [{"name": "a"}, {"name": "b"}]}

        def on_enter(option, index):
            selected.append(option["name"])
            return True

        with patch("builtins.input", return_value="2"):
            key_nav.navigate("Title", "Subtitle", [{"name": "a"}],
                             lambda option, i: option["name"], on_enter, "hint",
                             refresh_fn=refresh)

        self.assertEqual(selected, ["b"])

    def test_refreshed_subtitle_and_hint_are_rendered(self):
        """刷新返回的副标题与底部提示应被渲染，而非入参快照。"""
        buffer = io.StringIO()
        console = Console(file=buffer, width=80, force_terminal=False)

        def refresh():
            return {"options": [{"name": "a"}], "subtitle": "新鲜副标题", "hint": "新鲜提示"}

        with patch.object(key_nav, "_console", console), \
                patch("builtins.input", return_value="/back"):
            key_nav.navigate("Title", "OldSubtitle", [{"name": "a"}],
                             lambda option, i: option["name"],
                             lambda option, i: True, "OldHint",
                             refresh_fn=refresh)

        rendered = buffer.getvalue()
        self.assertIn("新鲜副标题", rendered)
        self.assertIn("新鲜提示", rendered)
        self.assertNotIn("OldSubtitle", rendered)
        self.assertNotIn("OldHint", rendered)


if __name__ == "__main__":
    unittest.main()
