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
