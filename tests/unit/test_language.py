"""language._visible_range 纯逻辑单元测试。

验证语言选择列表的窗口计算逻辑（total 与高度关系、居中、边界钳制），
通过 patch _list_window_size 固定终端高度，避免真实终端依赖。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_language -v
"""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.CLIserver.language import _visible_range


class TestVisibleRange(unittest.TestCase):
    """验证 _visible_range 窗口计算。"""

    @patch("modules.CLIserver.language._list_window_size", return_value=5)
    def test_all_visible_when_total_leq_height(self, _mock):
        self.assertEqual(_visible_range(2, 5), (0, 5))
        self.assertEqual(_visible_range(0, 3), (0, 3))

    @patch("modules.CLIserver.language._list_window_size", return_value=5)
    def test_centered_when_index_middle(self, _mock):
        # 高度 5，total 10：index=4 → start=2, end=7（居中）
        start, end = _visible_range(4, 10)
        self.assertEqual(start, 2)
        self.assertEqual(end, 7)
        self.assertEqual(end - start, 5)

    @patch("modules.CLIserver.language._list_window_size", return_value=5)
    def test_clamped_at_start(self, _mock):
        # 高度 5，total 10：index=0 → start 钳制为 0
        start, end = _visible_range(0, 10)
        self.assertEqual(start, 0)
        self.assertEqual(end, 5)

    @patch("modules.CLIserver.language._list_window_size", return_value=5)
    def test_clamped_at_end(self, _mock):
        # 高度 5，total 10：index=9 → start 钳制为 5，覆盖最后 5 条
        start, end = _visible_range(9, 10)
        self.assertEqual(start, 5)
        self.assertEqual(end, 10)

    @patch("modules.CLIserver.language._list_window_size", return_value=1)
    def test_single_height(self, _mock):
        start, end = _visible_range(3, 10)
        self.assertEqual(end - start, 1)
        self.assertLessEqual(start, 3)
        self.assertGreater(end, 3)


if __name__ == "__main__":
    unittest.main()
