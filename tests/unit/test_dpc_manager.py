"""dpc_manager 纯逻辑单元测试。

覆盖 is_path_allowed / filter_allowed_paths / _migrate_old_format，
其中 _migrate_old_format 为纯 dict 变换，其余使用临时目录构造 .dpc 文件，
不触网、不依赖真实工作目录。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_dpc_manager -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater import dpc_manager


def _write_dpc(work_dir, restricted):
    """直接写入 .dpc 文件（避免 ctypes 隐藏属性依赖）。"""
    data = {
        "dir_id": "test-dir",
        "conversations": [],
        "current": None,
        "restricted": restricted,
    }
    dpc_path = os.path.join(work_dir, dpc_manager.DPC_FILENAME)
    with open(dpc_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class TestIsPathAllowed(unittest.TestCase):
    """验证 is_path_allowed 的屏蔽规则匹配。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_default_allowed_when_no_dpc(self):
        allowed, msg = dpc_manager.is_path_allowed(self.tmp, "a.txt")
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_wildcard_blocks_everything(self):
        _write_dpc(self.tmp, ["*"])
        allowed, msg = dpc_manager.is_path_allowed(self.tmp, "a.txt")
        self.assertFalse(allowed)
        self.assertIn("禁止访问", msg)

    def test_pattern_matches_relative_path(self):
        _write_dpc(self.tmp, ["*.log"])
        allowed, _ = dpc_manager.is_path_allowed(self.tmp, "x.log")
        self.assertFalse(allowed)
        allowed, _ = dpc_manager.is_path_allowed(self.tmp, "x.txt")
        self.assertTrue(allowed)

    def test_pattern_matches_basename(self):
        _write_dpc(self.tmp, ["secret.txt"])
        allowed, _ = dpc_manager.is_path_allowed(self.tmp, "sub/secret.txt")
        self.assertFalse(allowed)

    def test_path_normalized_for_matching(self):
        _write_dpc(self.tmp, ["sub/*.txt"])
        allowed, _ = dpc_manager.is_path_allowed(self.tmp, "sub\\a.txt")
        self.assertFalse(allowed)

    def test_dpc_itself_blocked(self):
        _write_dpc(self.tmp, [".dpc"])
        allowed, _ = dpc_manager.is_path_allowed(self.tmp, ".dpc")
        self.assertFalse(allowed)


class TestFilterAllowedPaths(unittest.TestCase):
    """验证 filter_allowed_paths 的批量过滤。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_splits_allowed_and_blocked(self):
        _write_dpc(self.tmp, ["*.log"])
        allowed, blocked = dpc_manager.filter_allowed_paths(
            self.tmp, ["a.txt", "b.log", "c.md"]
        )
        self.assertEqual(allowed, ["a.txt", "c.md"])
        self.assertEqual(blocked, ["b.log"])


class TestMigrateOldFormat(unittest.TestCase):
    """验证 _migrate_old_format 的旧格式迁移。"""

    def test_passthrough_new_format(self):
        data = {
            "dir_id": "d1",
            "conversations": [{"id": "c1", "name": "对话"}],
            "current": "c1",
            "restricted": [".dpc"],
        }
        result = dpc_manager._migrate_old_format(data)
        self.assertIs(result, data)
        self.assertIn("restricted", result)

    def test_migrate_old_conversations_list(self):
        data = {"dir_id": "d1", "conversations": ["对话1", "对话2"], "current": "对话1"}
        result = dpc_manager._migrate_old_format(data)
        self.assertEqual(len(result["conversations"]), 2)
        self.assertIsInstance(result["conversations"][0], dict)
        self.assertIn("id", result["conversations"][0])
        self.assertEqual(result["conversations"][0]["name"], "对话1")
        self.assertEqual(result["current"], result["conversations"][0]["id"])

    def test_migrate_single_conversation(self):
        data = {"dir_id": "d1", "conversation": "仅此对话"}
        result = dpc_manager._migrate_old_format(data)
        self.assertEqual(len(result["conversations"]), 1)
        self.assertEqual(result["conversations"][0]["name"], "仅此对话")

    def test_migrate_restricted_default(self):
        data = {"dir_id": "d1"}
        result = dpc_manager._migrate_old_format(data)
        self.assertEqual(result["restricted"], [".dpc"])
        self.assertEqual(len(result["conversations"]), 0)


if __name__ == "__main__":
    unittest.main()
