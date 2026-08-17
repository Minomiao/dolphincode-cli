"""bootstrap.constants 常量完整性单元测试。

验证关键常量存在、类型与取值符合预期，防止误删或改动破坏依赖方。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_constants -v
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.bootstrap import constants


class TestConstants(unittest.TestCase):
    """验证核心常量存在且取值合理。"""

    def test_stream_limits(self):
        self.assertTrue(hasattr(constants, "STREAM_MAX_HARD_LIMIT"))
        self.assertTrue(hasattr(constants, "STREAM_INITIAL_MAX"))
        self.assertTrue(hasattr(constants, "STREAM_EXTEND_BY"))
        self.assertGreater(constants.STREAM_MAX_HARD_LIMIT, constants.STREAM_INITIAL_MAX)
        self.assertGreater(constants.STREAM_EXTEND_BY, 0)

    def test_context_thresholds(self):
        self.assertTrue(hasattr(constants, "WARN_THRESHOLD"))
        self.assertTrue(hasattr(constants, "HIGH_THRESHOLD"))
        self.assertTrue(hasattr(constants, "CRITICAL_THRESHOLD"))
        # 阈值递增：warn < high < critical
        self.assertLess(constants.WARN_THRESHOLD, constants.HIGH_THRESHOLD)
        self.assertLess(constants.HIGH_THRESHOLD, constants.CRITICAL_THRESHOLD)
        # 均为 0~1 比例
        for t in (constants.WARN_THRESHOLD, constants.HIGH_THRESHOLD, constants.CRITICAL_THRESHOLD):
            self.assertTrue(0 < t < 1)

    def test_event_and_action_identifiers(self):
        self.assertTrue(hasattr(constants, "EVENT_MAX_ITERATIONS_REACHED"))
        self.assertTrue(hasattr(constants, "ACTION_RUN_POWERSHELL_SCRIPT"))
        self.assertEqual(constants.EVENT_MAX_ITERATIONS_REACHED, "max_iterations_reached")
        self.assertEqual(constants.ACTION_RUN_POWERSHELL_SCRIPT, "run_powershell_script")

    def test_constant_types(self):
        # 阈值应为 float，流限制应为 int
        self.assertIsInstance(constants.WARN_THRESHOLD, float)
        self.assertIsInstance(constants.STREAM_MAX_HARD_LIMIT, int)

    def test_default_model(self):
        # 默认模型常量为非空字符串，且存在于模型注册表
        self.assertTrue(hasattr(constants, "DEFAULT_MODEL"))
        self.assertIsInstance(constants.DEFAULT_MODEL, str)
        self.assertGreater(len(constants.DEFAULT_MODEL), 0)
        self.assertIn(constants.DEFAULT_MODEL, constants.MODEL_REGISTRY)


if __name__ == "__main__":
    unittest.main()
