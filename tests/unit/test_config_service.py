"""config_service 配置服务单元测试。

使用假的 config / cmd / chat 模块验证各配置项的写入、
校验与重建行为，不触盘、不依赖真实配置文件。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_config_service -v
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.bootstrap import constants
from modules.core.services import config_service


class FakeChatInstance:
    """替代 DolphinChat 的假实例。"""

    def __init__(self):
        self.messages = []
        self.effort_level = "fine"
        self.save_target = None

    def set_save_target(self, dir_id, conv_id):
        self.save_target = (dir_id, conv_id)


class FakeChatModule:
    """替代 modules.chater.chat 的假模块。"""

    def __init__(self):
        self.instances = []

    def DolphinChat(self, model=None, max_tokens=None, callback=None):
        instance = FakeChatInstance()
        instance.model = model
        instance.max_tokens = max_tokens
        self.instances.append(instance)
        return instance


class FakeConfigModule:
    """替代 modules.main_server.config 的假模块，记录保存调用。"""

    def __init__(self):
        self.saved = []
        self.remove_results = []  # [(success, error)] 队列
        self.api_key_writes = []  # [(model_name, api_key)]
        self.model_updates = []  # [{name, description, base_url, context_window, api_key, vision}]
        self.update_result = None  # 非 None 时作为 update_custom_model 的返回值

    def save_config(self, config):
        self.saved.append(config)

    def remove_custom_model(self, name):
        if not self.remove_results:
            return True, ""
        return self.remove_results.pop(0)

    def set_model_api_key(self, name, api_key):
        self.api_key_writes.append((name, api_key))
        return True, ""

    def update_custom_model(self, name, description=None, base_url=None,
                            context_window=None, api_key=None, vision=None):
        self.model_updates.append({
            "name": name, "description": description, "base_url": base_url,
            "context_window": context_window, "api_key": api_key, "vision": vision,
        })
        if self.update_result is not None:
            return self.update_result
        return True, ""

    def resolve_model_credentials(self, name):
        """按模型名返回凭据：自定义模型用自身声明，内置模型用默认地址。"""
        if name == "my-model":
            return {"base_url": "https://example.com/v1", "api_key": "sk-x"}
        return {"base_url": "https://api.deepseek.com", "api_key": "sk-default"}


class FakeCmdModule:
    """替代命令模块的假模块。"""

    def __init__(self):
        self.save_calls = 0

    def save_commands(self):
        self.save_calls += 1


class FakeCtx:
    """满足 config_service 上下文协议的假上下文。"""

    def __init__(self):
        self.chat_module = FakeChatModule()
        self.config_module = FakeConfigModule()
        self.cmd_module = FakeCmdModule()
        self.current_config = {
            "model": constants.DEFAULT_MODEL,
            "max_tokens": 18000,
            "command_prefix": "/",
            "show_thinking": False,
            "effort_level": "fine",
        }
        self.chat_instance = self.chat_module.DolphinChat()
        self.chat = self.chat_module
        self.config = self.config_module
        self.cmd = self.cmd_module
        self.show_thinking = False
        self.effort_level = "fine"
        self.current_dir_id = None
        self.current_conv_id = None


class TestSetMaxTokens(unittest.TestCase):
    """最大 Token 数设置。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_valid_value_saved(self):
        result = config_service.set_max_tokens(self.ctx, 30000)
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.current_config["max_tokens"], 30000)
        self.assertEqual(len(self.ctx.config_module.saved), 1)

    def test_below_minimum_rejected(self):
        result = config_service.set_max_tokens(self.ctx, 0)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "min")
        self.assertEqual(self.ctx.current_config["max_tokens"], 18000)
        self.assertEqual(self.ctx.config_module.saved, [])

    def test_above_maximum_rejected(self):
        result = config_service.set_max_tokens(self.ctx, config_service.MAX_MAX_TOKENS + 1)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "max")
        self.assertEqual(self.ctx.config_module.saved, [])

    def test_boundary_values_accepted(self):
        self.assertTrue(config_service.set_max_tokens(self.ctx, 1)["success"])
        self.assertTrue(config_service.set_max_tokens(
            self.ctx, config_service.MAX_MAX_TOKENS)["success"])


class TestSetCommandPrefix(unittest.TestCase):
    """命令前缀设置。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_normal_prefix_saved(self):
        result = config_service.set_command_prefix(self.ctx, "!")
        self.assertTrue(result["success"])
        self.assertFalse(result["truncated"])
        self.assertEqual(self.ctx.current_config["command_prefix"], "!")
        self.assertEqual(self.ctx.cmd_module.save_calls, 1)
        self.assertEqual(len(self.ctx.config_module.saved), 1)

    def test_long_prefix_truncated(self):
        result = config_service.set_command_prefix(self.ctx, "abcdefghijk")
        self.assertTrue(result["success"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["value"], "abcdefghij")
        self.assertEqual(self.ctx.current_config["command_prefix"], "abcdefghij")


class TestDisplayPreferences(unittest.TestCase):
    """思考显示与思考深度设置。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_show_thinking_enabled(self):
        result = config_service.set_show_thinking(self.ctx, True)
        self.assertTrue(result["success"])
        self.assertTrue(result["changed"])
        self.assertTrue(self.ctx.show_thinking)
        self.assertTrue(self.ctx.current_config["show_thinking"])

    def test_show_thinking_unchanged(self):
        result = config_service.set_show_thinking(self.ctx, False)
        self.assertTrue(result["success"])
        self.assertFalse(result["changed"])
        # 未变更时不应写盘
        self.assertEqual(self.ctx.config_module.saved, [])

    def test_effort_level_valid(self):
        result = config_service.set_effort_level(self.ctx, "high")
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.effort_level, "high")
        self.assertEqual(self.ctx.chat_instance.effort_level, "high")
        self.assertEqual(self.ctx.current_config["effort_level"], "high")

    def test_effort_level_invalid(self):
        result = config_service.set_effort_level(self.ctx, "extreme")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid")
        self.assertEqual(self.ctx.effort_level, "fine")
        self.assertEqual(self.ctx.config_module.saved, [])

    def test_effort_syncs_missing_chat_instance(self):
        self.ctx.chat_instance = None
        result = config_service.set_effort_level(self.ctx, "normal")
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.effort_level, "normal")


class TestModelSwitch(unittest.TestCase):
    """模型切换与 API 密钥。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_switch_builtin_model(self):
        model_info = {"name": "other-model", "description": "测试"}
        result = config_service.switch_model(self.ctx, model_info)
        self.assertTrue(result["success"])
        self.assertEqual(result["value"], "other-model")
        self.assertEqual(self.ctx.current_config["model"], "other-model")
        # 内置模型解析到默认服务地址与 .env 密钥，不再沿用自定义模型凭据
        self.assertEqual(self.ctx.current_config["base_url"], "https://api.deepseek.com")
        self.assertEqual(self.ctx.current_config["api_key"], "sk-default")
        self.assertTrue(result["rebuilt"])
        # 切换后实例被重建
        self.assertEqual(len(self.ctx.chat_module.instances), 2)

    def test_switch_custom_model_applies_credentials(self):
        model_info = {
            "name": "my-model", "description": "自定义",
            "custom": True, "base_url": "https://example.com/v1", "api_key": "sk-x",
        }
        config_service.switch_model(self.ctx, model_info)
        self.assertEqual(self.ctx.current_config["base_url"], "https://example.com/v1")
        self.assertEqual(self.ctx.current_config["api_key"], "sk-x")
        self.assertEqual(len(self.ctx.config_module.saved), 1)

    def test_set_api_key_rebuilds(self):
        result = config_service.set_api_key(self.ctx, "sk-new")
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.current_config["api_key"], "sk-new")
        self.assertEqual(len(self.ctx.chat_module.instances), 2)

    def test_remove_custom_model_resets_current(self):
        self.ctx.current_config["model"] = "my-model"
        result = config_service.remove_custom_model(self.ctx, "my-model")
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.current_config["model"], constants.DEFAULT_MODEL)

    def test_remove_custom_model_keeps_other_current(self):
        self.ctx.current_config["model"] = "other-model"
        self.ctx.config_module.remove_results = [(False, "未找到自定义模型 'my-model'")]
        result = config_service.remove_custom_model(self.ctx, "my-model")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "未找到自定义模型 'my-model'")
        self.assertEqual(self.ctx.current_config["model"], "other-model")


class TestSetModelApiKey(unittest.TestCase):
    """按模型更新 API 密钥。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_current_model_syncs_and_rebuilds(self):
        result = config_service.set_model_api_key(
            self.ctx, constants.DEFAULT_MODEL, "sk-new")
        self.assertTrue(result["success"])
        self.assertTrue(result["rebuilt"])
        self.assertEqual(self.ctx.current_config["api_key"], "sk-new")
        self.assertEqual(len(self.ctx.chat_module.instances), 2)

    def test_other_model_writes_env_only(self):
        self.ctx.current_config["model"] = "other-model"
        result = config_service.set_model_api_key(self.ctx, "my-model", "sk-x")
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.config_module.api_key_writes, [("my-model", "sk-x")])
        self.assertNotIn("rebuilt", result)
        # 未切换当前模型，客户端不重建
        self.assertEqual(len(self.ctx.chat_module.instances), 1)


class TestUpdateModel(unittest.TestCase):
    """修改已有模型的配置。"""

    def setUp(self):
        self.ctx = FakeCtx()

    def test_key_only_on_current_model_rebuilds(self):
        result = config_service.update_model(self.ctx, constants.DEFAULT_MODEL,
                                             {"api_key": "sk-new"})
        self.assertTrue(result["success"])
        self.assertTrue(result["rebuilt"])
        self.assertEqual(self.ctx.current_config["api_key"], "sk-new")
        self.assertEqual(len(self.ctx.chat_module.instances), 2)
        # 仅改密钥走专用分支，不走通用字段更新
        self.assertEqual(self.ctx.config_module.model_updates, [])

    def test_fields_on_custom_model_persist_without_rebuild(self):
        self.ctx.current_config["model"] = "other-model"
        result = config_service.update_model(self.ctx, "my-model", {
            "description": "desc", "base_url": "https://x.example.com/v1",
            "context_window": 64000, "api_key": "sk-x"})
        self.assertTrue(result["success"])
        self.assertFalse(result["rebuilt"])
        self.assertEqual(len(self.ctx.chat_module.instances), 1)
        self.assertEqual(self.ctx.config_module.model_updates, [{
            "name": "my-model", "description": "desc",
            "base_url": "https://x.example.com/v1",
            "context_window": 64000, "api_key": "sk-x", "vision": None}])

    def test_fields_on_current_custom_model_rebuilds(self):
        self.ctx.current_config["model"] = "my-model"
        result = config_service.update_model(self.ctx, "my-model", {
            "description": "desc", "base_url": "https://x.example.com/v1"})
        self.assertTrue(result["rebuilt"])
        # 凭据按模型重新解析后写回内存
        self.assertEqual(self.ctx.current_config["base_url"], "https://example.com/v1")
        self.assertEqual(len(self.ctx.chat_module.instances), 2)

    def test_vision_toggle_passed_through(self):
        self.ctx.current_config["model"] = "other-model"
        result = config_service.update_model(self.ctx, "my-model", {"vision": True})
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.config_module.model_updates[0]["vision"], True)

    def test_vision_off_passed_through(self):
        self.ctx.current_config["model"] = "other-model"
        result = config_service.update_model(self.ctx, "my-model", {"vision": False})
        self.assertTrue(result["success"])
        self.assertEqual(self.ctx.config_module.model_updates[0]["vision"], False)

    def test_failure_returns_error(self):
        self.ctx.config_module.update_result = (False, "保存模型配置失败")
        result = config_service.update_model(self.ctx, "my-model",
                                             {"base_url": "https://x.example.com/v1"})
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "保存模型配置失败")
        self.assertEqual(len(self.ctx.chat_module.instances), 1)


class TestGetSettings(unittest.TestCase):
    """配置快照读取。"""

    def test_snapshot_fields(self):
        ctx = FakeCtx()
        snapshot = config_service.get_settings(ctx)
        self.assertEqual(snapshot["model"], constants.DEFAULT_MODEL)
        self.assertEqual(snapshot["max_tokens"], 18000)
        self.assertEqual(snapshot["command_prefix"], "/")
        self.assertFalse(snapshot["show_thinking"])
        self.assertEqual(snapshot["effort_level"], "fine")


if __name__ == "__main__":
    unittest.main()
