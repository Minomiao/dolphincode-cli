"""i18n 语言文件同步单元测试。

覆盖内置文案版本机制：文件缺失时生成、版本落后时刷新并备份、
版本一致时保留用户自定义、用户新增键始终保留。
所有文件操作重定向到临时目录。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_i18n -v
"""
import json
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

from modules.bootstrap import translations
from modules.CLIserver import i18n

ZH_HINT = translations.TRANSLATIONS["zh-CN"]["model.hint"]


class TestLanguageFileSync(unittest.TestCase):
    """语言文件按内置版本同步。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.lang_dir = Path(self._tmp.name)

        patcher = patch.object(i18n, "_get_language_dir", return_value=str(self.lang_dir))
        patcher.start()
        self.addCleanup(patcher.stop)

        self._previous = i18n._translations
        self.addCleanup(self._restore_translations)

    def _restore_translations(self):
        i18n._translations = self._previous
        self._tmp.cleanup()

    def _path(self, code="zh-CN"):
        return self.lang_dir / f"{code}.json"

    def _load(self, code="zh-CN"):
        """执行一次语言表加载并返回该语言文件的内容。"""
        i18n._load_translations()
        return json.loads(self._path(code).read_text(encoding="utf-8"))

    def test_missing_file_is_generated_with_version(self):
        data = self._load()
        self.assertEqual(data["_version"], translations.TRANSLATIONS_VERSION)
        self.assertEqual(data["model.hint"], ZH_HINT)

    def test_stale_file_is_refreshed_and_backed_up(self):
        self._path().write_text(json.dumps({"model.hint": "OLD-HINT"}, ensure_ascii=False),
                                encoding="utf-8")

        data = self._load()

        # 内置文案覆盖旧文件内容
        self.assertEqual(data["model.hint"], ZH_HINT)
        self.assertEqual(data["_version"], translations.TRANSLATIONS_VERSION)
        # 旧文件被备份，用户自定义内容可找回
        backup = self.lang_dir / "zh-CN.json.bak"
        self.assertTrue(backup.exists())
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8"))["model.hint"], "OLD-HINT")

    def test_same_version_keeps_user_edits(self):
        self._path().write_text(json.dumps({
            "_version": translations.TRANSLATIONS_VERSION,
            "model.hint": "MY-CUSTOM-HINT",
        }, ensure_ascii=False), encoding="utf-8")

        i18n._load_translations()

        self.assertEqual(i18n.t("model.hint"), "MY-CUSTOM-HINT")

    def test_custom_extra_keys_are_preserved(self):
        self._path().write_text(json.dumps({"my.custom.key": "keep-me"}, ensure_ascii=False),
                                encoding="utf-8")

        data = self._load()

        self.assertEqual(data["my.custom.key"], "keep-me")

    def test_new_builtin_keys_are_visible(self):
        i18n._load_translations()
        # 版本一致时新增键通过合并生效
        self.assertEqual(i18n.t("form.hint"), translations.TRANSLATIONS["zh-CN"]["form.hint"])


if __name__ == "__main__":
    unittest.main()
