"""file_operation 三处修复单元测试。

验证：
- _check_dpc_restriction 跨盘符（父目录与项目不同盘符）不再抛 ValueError，正常终止
- read_file 的 offset/limit 类型与范围校验（负数拒绝、非整数拒绝、limit 钳制）
- modify_file 写入前校验新内容大小（超 MAX_FILE_SIZE 拒绝且不改动原文件）

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_file_operation -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.functions.file_operation import (
    FileOperation,
    MAX_FILE_SIZE,
    _check_dpc_restriction,
)


class TestDpcCrossDrive(unittest.TestCase):
    """验证 _check_dpc_restriction 在跨盘符场景下不再崩溃。"""

    @patch("modules.chater.dpc_manager.is_path_allowed", return_value=(True, None))
    def test_cross_drive_does_not_raise(self, mock_allowed):
        # 项目位于 D:\\codes\\QuickAI，跨盘符路径（C 盘）的父目录
        # 与项目无公共路径，os.path.commonpath 会抛 ValueError。
        # 修复后应安全终止并放行（该路径本就无 .dpc 可查）。
        result = _check_dpc_restriction("C:\\work\\a\\b.txt")
        self.assertEqual(result, (True, None))

    def test_same_drive_returns_allowed(self):
        # 同盘符普通路径：无 .dpc 时放行
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_check_dpc_restriction(os.path.join(tmp, "f.txt")), (True, None))


class TestReadFileParams(unittest.TestCase):
    """验证 read_file 的 offset/limit 校验。"""

    def setUp(self):
        self.fo = FileOperation()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.file = self.tmp_path / "lines.txt"
        self.file.write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
        self.base = {
            "file_path": "lines.txt",
            "work_directory": str(self.tmp_path),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_negative_offset_rejected(self):
        result = self.fo.read_file({**self.base, "offset": -5})
        self.assertIn("error", result)
        self.assertIn("不能为负数", result["error"])

    def test_negative_limit_rejected(self):
        result = self.fo.read_file({**self.base, "limit": -1})
        self.assertIn("error", result)
        self.assertIn("不能为负数", result["error"])

    def test_non_integer_offset_rejected(self):
        result = self.fo.read_file({**self.base, "offset": "abc"})
        self.assertIn("error", result)
        self.assertIn("必须为整数", result["error"])

    def test_limit_clamped_to_max(self):
        result = self.fo.read_file({**self.base, "limit": 99999})
        self.assertTrue(result["success"])
        # limit 应被钳制到 MAX_LINE_COUNT（1100）
        self.assertEqual(result["limit"], min(99999, 1100))

    def test_offset_beyond_end_returns_empty(self):
        result = self.fo.read_file({**self.base, "offset": 100})
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "")

    def test_normal_read(self):
        result = self.fo.read_file({**self.base, "offset": 2, "limit": 3})
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "line2\nline3\nline4")


class TestModifyFileSize(unittest.TestCase):
    """验证 modify_file 写入前校验新内容大小。"""

    def setUp(self):
        self.fo = FileOperation()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.file = self.tmp_path / "target.txt"
        self.file.write_text("hello world", encoding="utf-8")
        self.base = {
            "file_path": "target.txt",
            "old_str": "world",
            "work_directory": str(self.tmp_path),
        }

    def tearDown(self):
        self._tmp.cleanup()

    @patch("modules.functions.file_operation.backup_manager.get_backup_manager", return_value=None)
    def test_oversized_new_content_rejected_without_write(self, _mock_backup):
        huge = "x" * (MAX_FILE_SIZE + 1)
        result = self.fo.modify_file({**self.base, "new_str": huge})
        self.assertIn("error", result)
        self.assertIn("修改后文件内容过大", result["error"])
        # 文件必须保持原样（拒绝发生在写入之前）
        self.assertEqual(self.file.read_text(encoding="utf-8"), "hello world")

    @patch("modules.functions.file_operation.backup_manager.get_backup_manager", return_value=None)
    def test_normal_modify_succeeds(self, _mock_backup):
        result = self.fo.modify_file({**self.base, "new_str": "Dolphin"})
        self.assertTrue(result["success"])
        self.assertEqual(self.file.read_text(encoding="utf-8"), "hello Dolphin")


if __name__ == "__main__":
    unittest.main()
