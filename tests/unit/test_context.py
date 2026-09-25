"""ContextManager 纯逻辑单元测试。

覆盖 prepare_messages / check_context_usage / update_usage_from_api / reset_usage，
不触网、不依赖配置，仅使用 stdlib unittest。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_context -v
"""
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.chater.context import ContextManager


class FakeUsage:
    """模拟 OpenAI 返回的 usage 对象（含 DeepSeek 缓存字段）。"""

    def __init__(self, prompt=0, completion=0, hit=None, miss=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        if hit is not None:
            self.prompt_cache_hit_tokens = hit
        if miss is not None:
            self.prompt_cache_miss_tokens = miss


class TestPrepareMessages(unittest.TestCase):
    """验证 prepare_messages 的消息构建逻辑。"""

    def setUp(self):
        self.cm = ContextManager(lambda: "系统提示")

    def test_prepend_system_when_missing(self):
        messages = [{"role": "user", "content": "你好"}]
        result = self.cm.prepare_messages(messages)
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[0]["content"], "系统提示")
        self.assertEqual(result[1]["content"], "你好")

    def test_no_duplicate_system(self):
        messages = [{"role": "system", "content": "已有系统"}, {"role": "user", "content": "你好"}]
        result = self.cm.prepare_messages(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["content"], "系统提示")
        self.assertEqual(result[1]["content"], "你好")

    def test_context_merged_into_content_without_polluting_source(self):
        messages = [{"role": "user", "content": "看文件", "_context": "工作目录: /tmp"}]
        result = self.cm.prepare_messages(messages)
        self.assertIn("工作目录: /tmp", result[1]["content"])
        # 发送列表里 _context 应被移除
        self.assertNotIn("_context", result[1])
        # 原消息的 _context 不应被污染
        self.assertEqual(messages[0]["_context"], "工作目录: /tmp")

    def test_dynamic_context_appended_to_last_user(self):
        cm = ContextManager(lambda: "系统提示", lambda: "努力程度: fine")
        messages = [
            {"role": "user", "content": "问题一"},
            {"role": "assistant", "content": "回答一"},
            {"role": "user", "content": "问题二"},
        ]
        result = cm.prepare_messages(messages)
        # 动态上下文追加到最后一条 user
        self.assertTrue(result[-1]["content"].endswith("\n\n努力程度: fine"))
        # 写回 _context 到原消息（保持 content 不变）
        self.assertEqual(messages[-1]["_context"], "努力程度: fine")
        self.assertEqual(messages[-1]["content"], "问题二")
        self.assertEqual(messages[0]["content"], "问题一")

    def test_dynamic_context_appends_new_message_when_no_user(self):
        cm = ContextManager(lambda: "系统提示", lambda: "努力程度: fine")
        result = cm.prepare_messages([])
        self.assertEqual(result[-1], {"role": "user", "content": "努力程度: fine"})

    def test_no_dynamic_context_when_getter_returns_empty(self):
        cm = ContextManager(lambda: "系统提示", lambda: None)
        messages = [{"role": "user", "content": "你好"}]
        result = cm.prepare_messages(messages)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["content"], "你好")


class TestSendFilter(unittest.TestCase):
    """验证 _send=False 消息的发送过滤与工具调用配对完整性。"""

    def setUp(self):
        self.cm = ContextManager(lambda: "系统提示")

    def test_user_message_skipped(self):
        messages = [
            {"role": "user", "content": "旧问题", "_send": False},
            {"role": "user", "content": "新问题"},
        ]
        result = self.cm.prepare_messages(messages)
        contents = [m.get("content") for m in result[1:]]
        self.assertEqual(contents, ["新问题"])

    def test_assistant_tool_pair_skipped_together(self):
        messages = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "", "_send": False, "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "t", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "结果"},
            {"role": "assistant", "content": "回答"},
        ]
        result = self.cm.prepare_messages(messages)
        roles = [m["role"] for m in result[1:]]
        self.assertEqual(roles, ["user", "assistant"])

    def test_tool_skipped_drops_assistant(self):
        messages = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call_1", "type": "function",
                 "function": {"name": "t", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "结果", "_send": False},
            {"role": "assistant", "content": "回答"},
        ]
        result = self.cm.prepare_messages(messages)
        roles = [m["role"] for m in result[1:]]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(result[-1]["content"], "回答")

    def test_context_written_back_to_correct_original_message(self):
        cm = ContextManager(lambda: "系统提示", lambda: "努力程度: fine")
        messages = [
            {"role": "user", "content": "被跳过", "_send": False},
            {"role": "user", "content": "保留"},
        ]
        cm.prepare_messages(messages)
        self.assertNotIn("_context", messages[0])
        self.assertEqual(messages[1]["_context"], "努力程度: fine")

    def test_context_write_back_with_system_first(self):
        cm = ContextManager(lambda: "系统提示", lambda: "ctx")
        messages = [
            {"role": "system", "content": "已有系统"},
            {"role": "user", "content": "问题"},
        ]
        cm.prepare_messages(messages)
        self.assertEqual(messages[1]["_context"], "ctx")
        self.assertEqual(messages[1]["content"], "问题")


class _FakePartsBuilder:
    """记录调用并返回固定图片块的构建器。"""

    def __init__(self):
        self.calls = []

    def __call__(self, images):
        self.calls.append(list(images))
        return [{"type": "image_url", "image_url": {"url": f"https://x/{len(self.calls)}.png"}}]


class TestImageParts(unittest.TestCase):
    """验证 _images 消息的 parts 转换与降级。"""

    IMAGES = [{"path": "/tmp/a.png", "media_type": "image/png"}]

    def setUp(self):
        self.builder = _FakePartsBuilder()
        self.cm = ContextManager(lambda: "系统提示")
        self.cm.image_parts_builder = self.builder

    def test_vision_model_converts_to_parts(self):
        self.cm.vision_enabled = True
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES}]
        result = self.cm.prepare_messages(messages)
        content = result[1]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[0], {"type": "text", "text": "看图"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(self.builder.calls, [self.IMAGES])

    def test_non_vision_model_degrades_to_text(self):
        self.cm.vision_enabled = False
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES}]
        result = self.cm.prepare_messages(messages)
        self.assertEqual(result[1]["content"], "看图")
        self.assertEqual(self.builder.calls, [])

    def test_no_builder_keeps_message_untouched(self):
        cm = ContextManager(lambda: "系统提示")
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES}]
        result = cm.prepare_messages(messages)
        self.assertEqual(result[1]["content"], "看图")

    def test_images_merged_with_context(self):
        self.cm.vision_enabled = True
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES,
                     "_context": "工作目录: /tmp"}]
        result = self.cm.prepare_messages(messages)
        content = result[1]["content"]
        self.assertEqual(content[0]["text"], "看图\n\n工作目录: /tmp")
        self.assertEqual(len(content), 2)

    def test_dynamic_context_appended_to_parts_content(self):
        cm = ContextManager(lambda: "系统提示", lambda: "ctx")
        cm.image_parts_builder = self.builder
        cm.vision_enabled = True
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES}]
        result = cm.prepare_messages(messages)
        content = result[1]["content"]
        self.assertTrue(content[0]["text"].endswith("\n\nctx"))
        # 写回 _context 不污染原消息 content
        self.assertEqual(messages[0]["content"], "看图")
        self.assertEqual(messages[0]["_context"], "ctx")

    def test_source_message_not_mutated(self):
        self.cm.vision_enabled = True
        messages = [{"role": "user", "content": "看图", "_images": self.IMAGES}]
        self.cm.prepare_messages(messages)
        self.assertEqual(messages[0]["content"], "看图")
        self.assertEqual(messages[0]["_images"], self.IMAGES)


class TestUpdateUsage(unittest.TestCase):
    """验证 update_usage_from_api 的 token 统计。"""

    def setUp(self):
        self.cm = ContextManager(lambda: "系统提示")

    def test_ignore_none(self):
        self.cm.update_usage_from_api(None)
        self.assertEqual(self.cm._turn_count, 0)
        self.assertEqual(self.cm._cumulative_prompt_tokens, 0)

    def test_cumulative_prompt_and_completion(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20))
        self.assertEqual(self.cm._turn_count, 1)
        self.assertEqual(self.cm._cumulative_prompt_tokens, 100)
        self.assertEqual(self.cm._cumulative_completion_tokens, 20)

    def test_previous_prompt_tracked(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20))
        self.cm.update_usage_from_api(FakeUsage(prompt=150, completion=30))
        self.assertEqual(self.cm._previous_prompt_tokens, 100)
        self.assertEqual(self.cm._cumulative_prompt_tokens, 150)
        self.assertEqual(self.cm._turn_count, 2)

    def test_cache_hit_miss(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20, hit=80, miss=20))
        self.assertEqual(self.cm._cache_hit_tokens, 80)
        self.assertEqual(self.cm._cache_miss_tokens, 20)

    def test_reset_usage(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20, hit=80, miss=20))
        self.cm.reset_usage()
        self.assertEqual(self.cm._turn_count, 0)
        self.assertEqual(self.cm._cumulative_prompt_tokens, 0)
        self.assertEqual(self.cm._cache_hit_tokens, 0)


class TestCheckContextUsage(unittest.TestCase):
    """验证 check_context_usage 的告警判定与统计输出。"""

    def setUp(self):
        self.cm = ContextManager(lambda: "系统提示")

    def test_returns_all_keys(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20))
        info = self.cm.check_context_usage([], context_window=1000)
        expected_keys = {
            "usage_ratio", "context_window", "estimated_tokens", "level", "source",
            "prompt_tokens", "completion_tokens", "turn_prompt_tokens",
            "turn_completion_tokens", "cache_hit_tokens", "cache_miss_tokens",
            "cache_hit_ratio", "turn_count",
        }
        self.assertEqual(set(info), expected_keys)
        self.assertEqual(info["context_window"], 1000)
        self.assertEqual(info["estimated_tokens"], 120)

    def test_level_none_when_low_usage(self):
        self.cm.update_usage_from_api(FakeUsage(prompt=100, completion=20))
        info = self.cm.check_context_usage([], context_window=10000)
        self.assertIsNone(info["level"])

    def test_level_warn_when_high_ratio(self):
        # 使用真实阈值构造比例：7500/10000 = 75% > WARN_THRESHOLD(0.70)
        from modules.bootstrap import constants
        self.cm.update_usage_from_api(FakeUsage(prompt=7500, completion=0))
        info = self.cm.check_context_usage([], context_window=10000)
        self.assertEqual(info["level"], "warn")

    def test_estimated_source_without_api_usage(self):
        messages = [{"role": "user", "content": "你好"}]
        info = self.cm.check_context_usage(messages, context_window=10000)
        self.assertEqual(info["source"], "estimated")
        self.assertGreater(info["estimated_tokens"], 0)

    def test_cache_ratio_zero_when_no_cache(self):
        info = self.cm.check_context_usage([], context_window=10000)
        self.assertEqual(info["cache_hit_ratio"], 0)


if __name__ == "__main__":
    unittest.main()
