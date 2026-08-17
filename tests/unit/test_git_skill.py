"""git skill -- 分隔符单元测试。

验证 git_diff / git_add 对路径参数使用 "--" 分隔符，
防止以 "-" 开头的路径被当作 git 选项（如 git add -p 进入交互模式挂起）。
通过 patch _run_git 捕获实际传入的命令参数，不执行真实 git。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_git_skill -v
"""
import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

_SKILL_PATH = os.path.join(PROJECT_ROOT, "skills", "git", "skill.py")
_spec = importlib.util.spec_from_file_location("skills.git.skill", _SKILL_PATH)
git_skill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(git_skill)


class FakeContext:
    """模拟 skill_context：filter_allowed_paths 放行指定路径。"""

    def __init__(self, allowed):
        self._allowed = allowed

    def filter_allowed_paths(self, paths):
        return self._allowed, []

    def log_warning(self, message):
        pass


class TestGitDashSeparator(unittest.TestCase):
    """验证 diff/add 使用 -- 分隔符。"""

    def _capture_run_git(self):
        captured = {}

        def fake_run_git(context, args):
            captured["args"] = list(args)
            return {"success": True, "stdout": ""}

        return captured, fake_run_git

    def test_diff_dash_leading_path_uses_separator(self):
        captured, fake = self._capture_run_git()
        with patch.object(git_skill, "_run_git", side_effect=fake):
            git_skill.git_diff(FakeContext([]), "-p")
        self.assertEqual(captured["args"], ["diff", "--", "-p"])

    def test_diff_no_path_passes_plain_args(self):
        captured, fake = self._capture_run_git()
        with patch.object(git_skill, "_run_git", side_effect=fake):
            git_skill.git_diff(FakeContext([]), None)
        self.assertEqual(captured["args"], ["diff"])

    def test_diff_normal_path_uses_separator(self):
        captured, fake = self._capture_run_git()
        with patch.object(git_skill, "_run_git", side_effect=fake):
            git_skill.git_diff(FakeContext([]), "src/foo.py")
        self.assertEqual(captured["args"], ["diff", "--", "src/foo.py"])

    def test_add_dash_leading_path_uses_separator(self):
        captured, fake = self._capture_run_git()
        with patch.object(git_skill, "_run_git", side_effect=fake):
            git_skill.git_add(FakeContext(["-file"]), "-file")
        self.assertEqual(captured["args"], ["add", "--", "-file"])

    def test_add_multiple_paths_uses_separator(self):
        captured, fake = self._capture_run_git()
        with patch.object(git_skill, "_run_git", side_effect=fake):
            git_skill.git_add(FakeContext(["a.txt", "b.txt"]), "a.txt, b.txt")
        self.assertEqual(captured["args"], ["add", "--", "a.txt", "b.txt"])


if __name__ == "__main__":
    unittest.main()
