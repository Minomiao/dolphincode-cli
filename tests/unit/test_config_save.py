"""config.save_config api_key 覆盖单元测试。

验证清空 api_key 时也会写入 .env 覆盖旧值，避免 .env 残留旧密钥。
所有路径重定向到临时目录，不触碰真实配置与环境变量。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_config_save -v
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

from modules.main_server import config


class TestSaveConfigApiKeyOverride(unittest.TestCase):
    """验证 save_config 对 api_key 的空值覆盖行为。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.env_file = self.tmp_dir / ".env"
        self.config_file = self.tmp_dir / "config.json"
        self.date_dir = self.tmp_dir / "date"

        # 预置含旧密钥的 .env
        self.env_file.write_text("QUICKAI_API_KEY=old_secret_key\n", encoding="utf-8")

        patcher = patch.multiple(
            "modules.bootstrap",
            ENV_FILE=str(self.env_file),
            CONFIG_FILE=str(self.config_file),
            DATE_DIR=str(self.date_dir),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _env_content(self):
        return self.env_file.read_text(encoding="utf-8")

    def test_empty_api_key_overwrites_env(self):
        with patch("modules.main_server.config.load_dotenv") as mock_load:
            config.save_config({"api_key": "", "work_directory": "workplace"})

        content = self._env_content()
        self.assertNotIn("old_secret_key", content)
        self.assertIn("QUICKAI_API_KEY=", content)

    def test_nonempty_api_key_written(self):
        with patch("modules.main_server.config.load_dotenv") as mock_load:
            config.save_config({"api_key": "new_secret_key", "work_directory": "workplace"})

        self.assertIn("QUICKAI_API_KEY='new_secret_key'", self._env_content())

    def test_config_json_written_without_secrets(self):
        with patch("modules.main_server.config.load_dotenv") as mock_load:
            config.save_config({"api_key": "k", "work_directory": "w", "model": "m"})

        self.assertTrue(self.config_file.exists())
        content = self.config_file.read_text(encoding="utf-8")
        self.assertIn('"model"', content)
        self.assertNotIn("api_key", content)
        self.assertNotIn("work_directory", content)


if __name__ == "__main__":
    unittest.main()
