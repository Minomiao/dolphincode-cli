"""config.save_config 持久化分流单元测试。

验证：
- 清空 api_key 时也会写入 .env 覆盖旧值，避免 .env 残留旧密钥
- model / base_url 写入 models.json，不再落在 config.json
所有路径重定向到临时目录，不触碰真实配置与环境变量。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_config_save -v
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

from modules.main_server import config


class TestSaveConfigApiKeyOverride(unittest.TestCase):
    """验证 save_config 对 api_key 的空值覆盖行为。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_dir = Path(self._tmp.name)
        self.env_file = self.tmp_dir / ".env"
        self.config_file = self.tmp_dir / "config.json"
        self.models_file = self.tmp_dir / "models.json"
        self.date_dir = self.tmp_dir / "date"

        # 预置含旧密钥的 .env
        self.env_file.write_text("QUICKAI_API_KEY=old_secret_key\n", encoding="utf-8")

        patcher = patch.multiple(
            "modules.bootstrap",
            ENV_FILE=str(self.env_file),
            CONFIG_FILE=str(self.config_file),
            MODELS_FILE=str(self.models_file),
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

    def test_model_fields_routed_to_models_file(self):
        with patch("modules.main_server.config.load_dotenv") as mock_load:
            config.save_config({"api_key": "k", "work_directory": "w",
                                "model": "deepseek-v4-pro"})

        self.assertTrue(self.config_file.exists())
        config_content = self.config_file.read_text(encoding="utf-8")
        self.assertNotIn("api_key", config_content)
        self.assertNotIn("work_directory", config_content)
        self.assertNotIn('"model"', config_content)
        self.assertNotIn("base_url", config_content)

        self.assertTrue(self.models_file.exists())
        models_data = json.loads(self.models_file.read_text(encoding="utf-8"))
        self.assertEqual(models_data["current"], "deepseek-v4-pro")
        names = [m["name"] for m in models_data["models"]]
        self.assertIn("deepseek-flash", names)
        self.assertIn("deepseek-v4-pro", names)
        # 服务地址随模型条目存放，内置模型自带默认地址
        flash = next(m for m in models_data["models"] if m["name"] == "deepseek-flash")
        self.assertEqual(flash["base_url"], "https://api.deepseek.com")
        self.assertTrue(flash.get("builtin"))

    def test_load_config_resolves_builtin_credentials(self):
        """内置模型从模型条目的 base_url 与 .env 解析服务地址和密钥。"""
        # 旧结构（顶层 base_url）也会被规整为统一清单
        self.models_file.write_text(
            json.dumps({"current": "deepseek-flash", "base_url": "https://builtin.example.com"}),
            encoding="utf-8")
        with patch.dict(os.environ, {"QUICKAI_API_KEY": "env-key"}):
            loaded = config.load_config()

        self.assertEqual(loaded["model"], "deepseek-flash")
        self.assertEqual(loaded["base_url"], "https://builtin.example.com")
        self.assertEqual(loaded["api_key"], "env-key")

    def test_load_config_resolves_custom_model_credentials(self):
        """自定义模型用自身条目的 base_url，密钥按 api_key_env 从 .env 读取。"""
        self.models_file.write_text(
            json.dumps({
                "current": "my-model",
                "models": [
                    {"name": "my-model", "base_url": "https://custom.example.com/v1",
                     "api_key_env": "QUICKAI_API_KEY_MY_MODEL",
                     "context_window": 64000, "custom": True},
                ],
            }, ensure_ascii=False),
            encoding="utf-8")
        with patch.dict(os.environ, {"QUICKAI_API_KEY_MY_MODEL": "sk-custom"}):
            loaded = config.load_config()

        self.assertEqual(loaded["base_url"], "https://custom.example.com/v1")
        self.assertEqual(loaded["api_key"], "sk-custom")

    def test_add_custom_model_writes_key_to_env_only(self):
        """添加自定义模型时密钥只进 .env，models.json 只留映射变量名。"""
        config.init()
        with patch("modules.main_server.config.load_dotenv"):
            success, error = config.add_custom_model(
                "my-model", "自定义", "https://custom.example.com/v1", "sk-secret")
        self.assertTrue(success, error)

        models_data = json.loads(self.models_file.read_text(encoding="utf-8"))
        entry = next(m for m in models_data["models"] if m["name"] == "my-model")
        self.assertNotIn("api_key", entry)
        self.assertEqual(entry["api_key_env"], "QUICKAI_API_KEY_MY_MODEL")

        env_content = self._env_content()
        self.assertIn("QUICKAI_API_KEY_MY_MODEL", env_content)
        self.assertIn("sk-secret", env_content)

    def test_remove_custom_model_cleans_env_key(self):
        """删除自定义模型后清理它在 .env 中的密钥变量。"""
        config.init()
        with patch("modules.main_server.config.load_dotenv"):
            config.add_custom_model("my-model", "自定义", "https://custom.example.com/v1", "sk-secret")
            success, error = config.remove_custom_model("my-model")
        self.assertTrue(success, error)

        models_data = json.loads(self.models_file.read_text(encoding="utf-8"))
        self.assertNotIn("my-model", [m["name"] for m in models_data["models"]])
        self.assertNotIn("QUICKAI_API_KEY_MY_MODEL", self._env_content())
        # 默认变量不受影响
        self.assertIn("QUICKAI_API_KEY", self._env_content())

    def test_context_window_covers_custom_model(self):
        """自定义模型的 context_window 参与用量统计，而非回退默认值。"""
        self.models_file.write_text(
            json.dumps({
                "current": "my-model",
                "models": [
                    {"name": "my-model", "base_url": "https://custom.example.com/v1",
                     "api_key_env": "QUICKAI_API_KEY_MY_MODEL",
                     "context_window": 64000, "custom": True},
                ],
            }, ensure_ascii=False),
            encoding="utf-8")
        self.assertEqual(config.get_context_window("my-model"), 64000)
        self.assertEqual(config.get_context_window("deepseek-flash"), 1000000)
        self.assertEqual(config.get_context_window("unknown-model"), config.DEFAULT_CONTEXT_WINDOW)

    def test_user_edit_to_builtin_entry_wins(self):
        """已存在的条目以文件为准，不被内置种子覆盖。"""
        self.models_file.write_text(
            json.dumps({
                "current": "deepseek-flash",
                "models": [{"name": "deepseek-flash", "base_url": "https://edited.example.com",
                            "context_window": 7777, "builtin": True}],
            }, ensure_ascii=False),
            encoding="utf-8")
        config.init()

        models_data = json.loads(self.models_file.read_text(encoding="utf-8"))
        flash = next(m for m in models_data["models"] if m["name"] == "deepseek-flash")
        self.assertEqual(flash["base_url"], "https://edited.example.com")
        self.assertEqual(flash["context_window"], 7777)
        # 缺失的内置模型仍会补入
        self.assertIn("deepseek-v4-pro", [m["name"] for m in models_data["models"]])

    def test_builtin_model_cannot_be_removed(self):
        config.init()
        success, error = config.remove_custom_model("deepseek-flash")
        self.assertFalse(success)
        self.assertIn("不可删除", error)

    def test_migrate_legacy_files(self):
        """旧版分散数据迁移到 models.json，密钥搬到 .env 并改为映射。"""
        self.config_file.write_text(
            json.dumps({"model": "legacy-model", "base_url": "https://legacy.example.com",
                        "language": "zh-CN"}, ensure_ascii=False),
            encoding="utf-8")
        legacy_custom = self.date_dir
        legacy_custom.mkdir(parents=True, exist_ok=True)
        (legacy_custom / "custom_models.json").write_text(
            json.dumps([{"name": "legacy-model", "base_url": "https://legacy.example.com",
                         "api_key": "sk-legacy", "custom": True}], ensure_ascii=False),
            encoding="utf-8")

        with patch("modules.main_server.config.load_dotenv"):
            config.init()

        models_data = json.loads(self.models_file.read_text(encoding="utf-8"))
        self.assertEqual(models_data["current"], "legacy-model")
        names = [m["name"] for m in models_data["models"]]
        self.assertIn("legacy-model", names)
        # 内置种子沿用旧版顶层 base_url
        flash = next(m for m in models_data["models"] if m["name"] == "deepseek-flash")
        self.assertEqual(flash["base_url"], "https://legacy.example.com")
        # 自定义条目里的明文密钥被搬到 .env，条目只留映射变量名
        entry = next(m for m in models_data["models"] if m["name"] == "legacy-model")
        self.assertNotIn("api_key", entry)
        self.assertEqual(entry["api_key_env"], "QUICKAI_API_KEY_LEGACY_MODEL")
        self.assertIn("sk-legacy", self._env_content())
        # 内置条目共享默认变量
        self.assertEqual(flash["api_key_env"], "QUICKAI_API_KEY")
        # config.json 中已迁移的字段被清理
        config_content = self.config_file.read_text(encoding="utf-8")
        self.assertNotIn('"model"', config_content)
        self.assertNotIn("base_url", config_content)
        self.assertIn('"language"', config_content)


if __name__ == "__main__":
    unittest.main()
