"""calculator skill 纯逻辑单元测试。

覆盖 _is_safe_expression 字符白名单与 calculate 的合法/非法表达式处理。
skill 通过 importlib 按文件路径加载（与 SkillManager 加载方式一致），
不触网、不执行外部进程。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_calculator -v
"""
import importlib.util
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

_SKILL_PATH = os.path.join(PROJECT_ROOT, "skills", "calculator", "skill.py")
_spec = importlib.util.spec_from_file_location("skills.calculator.skill", _SKILL_PATH)
calculator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calculator)


class TestIsSafeExpression(unittest.TestCase):
    """验证表达式字符白名单。"""

    def test_math_expression_allowed(self):
        for expr in ["2+3*4", "sqrt(16)", "sin(pi/2)", "log(100, 10)", "factorial(5)", "3^2", "1.5e3", "10 % 3"]:
            self.assertTrue(calculator._is_safe_expression(expr), f"应允许: {expr}")

    def test_injection_rejected(self):
        for expr in ["__import__('os')", "1; import os", "eval('1')", "open('x')", "'string'", "b\"str\""]:
            self.assertFalse(calculator._is_safe_expression(expr), f"应拒绝: {expr}")

    def test_assignment_passes_whitelist_but_fails_parse(self):
        # "=" 在字符白名单内（比较表达式），白名单放行但 sympify 无法解析
        self.assertTrue(calculator._is_safe_expression("a=b"))
        result = calculator.calculate("a=b")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_whitespace_and_empty(self):
        self.assertTrue(calculator._is_safe_expression(" 2 + 3 "))
        self.assertFalse(calculator._is_safe_expression(""))


class TestCalculate(unittest.TestCase):
    """验证 calculate 的求值与错误处理。"""

    @unittest.skipUnless(calculator.HAS_SYMPY, "sympy 未安装")
    def test_basic_arithmetic(self):
        result = calculator.calculate("2+3*4")
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], 14)

    @unittest.skipUnless(calculator.HAS_SYMPY, "sympy 未安装")
    def test_integer_result_normalized(self):
        # sympy 的 N() 可能返回 Float(4.0)，skill 的整数归一化取决于
        # `sympy_result == int(sympy_result)` 比较，故只断言数值相等
        result = calculator.calculate("sqrt(16)")
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], 4)

    @unittest.skipUnless(calculator.HAS_SYMPY, "sympy 未安装")
    def test_float_result(self):
        result = calculator.calculate("sqrt(2)")
        self.assertTrue(result["success"])
        self.assertIsInstance(result["result"], float)

    def test_invalid_expression_rejected(self):
        result = calculator.calculate("__import__('os')")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    @unittest.skipUnless(calculator.HAS_SYMPY, "sympy 未安装")
    def test_unparsable_expression(self):
        result = calculator.calculate("2+")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_unsafe_without_sympy(self):
        with unittest.mock.patch.object(calculator, "HAS_SYMPY", False):
            result = calculator.calculate("2+2")
        self.assertFalse(result["success"])
        self.assertIn("sympify 未安装", result["error"])


if __name__ == "__main__":
    unittest.main()
