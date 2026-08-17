"""backup_actions.backup_file 备份文件名毫秒精度单元测试。

验证备份文件名包含微秒时间戳（%Y%m%d_%H%M%S%f），
避免同一秒内重复备份相互覆盖。文件操作仅在临时目录内进行。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_backup_actions -v
"""
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.functions.backup_actions import backup_file

# 备份文件名：8 位日期 + 6 位时间 + 6 位微秒 + .bak
_BACKUP_NAME_PATTERN = re.compile(r"^\d{8}_\d{12}\.bak$")


class TestBackupFilenameMicroseconds(unittest.TestCase):
    """验证备份文件名含微秒精度时间戳。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 备份注册表根目录重定向到临时目录，避免触碰真实会话数据
        patcher = patch("modules.functions.registry.CONVERSATIONS_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

        # 待备份源文件
        self.work_dir = self.root / "work"
        self.work_dir.mkdir()
        self.source = self.work_dir / "target.txt"
        self.source.write_text("hello", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _collect_backup_files(self):
        """收集临时根目录下所有 .bak 文件"""
        return [p for p in self.root.rglob("*.bak")]

    def test_backup_filename_has_microseconds(self):
        result = backup_file("target.txt", str(self.work_dir), "conv", "conv")
        self.assertIsNotNone(result)

        backup_files = self._collect_backup_files()
        self.assertEqual(len(backup_files), 1)
        self.assertRegex(backup_files[0].name, _BACKUP_NAME_PATTERN,
                         f"备份文件名应含微秒时间戳: {backup_files[0].name}")

    def test_create_action_skips_backup(self):
        result = backup_file("target.txt", str(self.work_dir), "conv", "conv", action="create")
        self.assertIsNone(result)
        self.assertEqual(self._collect_backup_files(), [])

    def test_nonexistent_file_skips_backup(self):
        result = backup_file("missing.txt", str(self.work_dir), "conv", "conv")
        self.assertIsNone(result)
        self.assertEqual(self._collect_backup_files(), [])


if __name__ == "__main__":
    unittest.main()
