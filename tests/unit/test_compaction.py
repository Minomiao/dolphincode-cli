"""compaction 纯逻辑单元测试。

覆盖分组、释放量预检、决策解析、应用打标与摘要插入，
不触网、不依赖 API，仅使用 stdlib unittest（AI 调用以 stub 替换）。

运行方式（在项目根目录执行）：
    venv\\Scripts\\python.exe -m unittest tests.unit.test_compaction -v
"""
import asyncio
import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from modules.bootstrap import init as bootstrap_init

bootstrap_init(PROJECT_ROOT)

from modules.bootstrap import constants
from modules.chater import compaction
from modules.chater.context import _filter_sendable


def _make_messages():
    """构造典型对话：system + 3 组（user 起组，含工具调用组）+ 当前回合组。"""
    return [
        {"role": "system", "content": "系统提示"},
        # 组 0
        {"role": "user", "content": "第一个任务"},
        {"role": "assistant", "content": "好的"},
        # 组 1（含工具调用）
        {"role": "user", "content": "读文件"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "文件内容"},
        {"role": "assistant", "content": "读完了"},
        # 组 2
        {"role": "user", "content": "第二个任务"},
        {"role": "assistant", "content": "完成"},
        # 组 3（当前回合，受保护）
        {"role": "user", "content": "当前问题"},
    ]


class FakeChat:
    """最小可用的 chat 替身：仅提供 compact_history 需要的接口。"""

    def __init__(self, messages):
        self.messages = messages
        self.model = "test-model"
        self.current_work_directory = PROJECT_ROOT
        self.saved = False
        self.events = []
        # prepare_messages 的替身：只返回 [system] + 消息（模拟发送列表）
        self.context = _FakeContext()

    def _save_now(self):
        self.saved = True

    async def _call_callback(self, event_type, data):
        self.events.append((event_type, data))


class _FakeContext:
    """ContextManager 替身：prepare_messages 返回 system + 原消息。"""

    def prepare_messages(self, messages):
        return [{"role": "system", "content": "系统提示"}] + [
            m for m in messages if m.get("role") != "system"
        ]


class TestBuildGroups(unittest.TestCase):
    """验证按「一次 user 到下一次 user」分组。"""

    def test_groups_split_by_user(self):
        groups = compaction.build_groups(_make_messages())
        self.assertEqual(len(groups), 4)
        # 组 0: user + assistant（索引 1-2）
        self.assertEqual((groups[0]["start"], groups[0]["end"]), (1, 2))
        # 组 1: user + assistant(tool_calls) + tool + assistant（索引 3-6）
        self.assertEqual((groups[1]["start"], groups[1]["end"]), (3, 6))
        self.assertEqual(len(groups[1]["messages"]), 4)
        # 组 3: 仅当前 user
        self.assertEqual(len(groups[3]["messages"]), 1)

    def test_skips_send_false_and_system(self):
        msgs = _make_messages()
        msgs[2][constants.MSG_SEND_FIELD] = False  # 组 0 的 assistant 已裁剪
        groups = compaction.build_groups(msgs)
        self.assertEqual(len(groups[0]["messages"]), 1)
        # 组号连续
        self.assertEqual([g["index"] for g in groups], [0, 1, 2, 3])


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(compaction._extract_json('{"keep": [0]}'), {"keep": [0]})

    def test_json_with_prose(self):
        text = '分析如下：\n{"keep": [0], "delete": [2], "goal": "g"}\n以上。'
        self.assertEqual(compaction._extract_json(text)["goal"], "g")

    def test_invalid_returns_none(self):
        self.assertIsNone(compaction._extract_json("没有 JSON"))
        self.assertIsNone(compaction._extract_json("[1,2,3]"))
        self.assertIsNone(compaction._extract_json(""))


class TestApply(unittest.TestCase):
    """验证打标、摘要插入与 keep 优先规则。"""

    def test_apply_marks_send_false_and_inserts_summary(self):
        msgs = _make_messages()
        chat = FakeChat(msgs)
        groups = compaction.build_groups(msgs)
        candidates = groups[:-1]
        decisions = {"keep": [1], "delete": [0], "goal": "测试任务"}
        stats = compaction._apply(chat, candidates, decisions, "整体摘要", ["archive_a"])

        # keep 组 1 原样保留
        self.assertNotIn(constants.MSG_SEND_FIELD, chat.messages[3])
        # delete 组 0 打标
        self.assertIs(chat.messages[1].get(constants.MSG_SEND_FIELD), False)
        self.assertIs(chat.messages[2].get(constants.MSG_SEND_FIELD), False)
        # 摘要消息插入在第一个摘要组（组 2）的起始位置，_display=False
        summary_msg = chat.messages[7]
        self.assertEqual(summary_msg["role"], "user")
        self.assertIn("整体摘要", summary_msg["content"])
        self.assertIn("archive_a", summary_msg["content"])
        self.assertIs(summary_msg.get(constants.MSG_DISPLAY_FIELD), False)
        # 组 2 原文被打标但保留在列表中（回显原样）
        self.assertIs(chat.messages[8].get(constants.MSG_SEND_FIELD), False)
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["summarized"], 1)

    def test_keep_wins_over_delete(self):
        msgs = _make_messages()
        chat = FakeChat(msgs)
        groups = compaction.build_groups(msgs)
        decisions = {"keep": [0], "delete": [0], "goal": "g"}
        stats = compaction._apply(chat, groups[:-1], decisions, "摘要", [])
        self.assertNotIn(constants.MSG_SEND_FIELD, chat.messages[1])
        self.assertEqual(stats["kept"], 1)
        self.assertEqual(stats["deleted"], 0)

    def test_out_of_range_ids_ignored(self):
        msgs = _make_messages()
        chat = FakeChat(msgs)
        groups = compaction.build_groups(msgs)
        decisions = {"keep": [99], "delete": [-1], "goal": "g"}
        stats = compaction._apply(chat, groups[:-1], decisions, "摘要", [])
        self.assertEqual(stats["kept"], 0)
        self.assertEqual(stats["deleted"], 0)

    def test_sendable_pairs_intact_after_apply(self):
        """整理后 _filter_sendable 仍输出合法的工具调用配对。"""
        msgs = _make_messages()
        chat = FakeChat(msgs)
        groups = compaction.build_groups(msgs)
        decisions = {"keep": [], "delete": [0], "goal": "g"}
        compaction._apply(chat, groups[:-1], decisions, "摘要", [])
        sendable = _filter_sendable([m for m in chat.messages if m.get("role") != "system"])
        # 保留的 assistant(tool_calls) 必须有对应 tool 回复
        for i, (idx, msg) in enumerate(sendable):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                following = [sendable[j][1] for j in range(i + 1, len(sendable))]
                tool_replies = [m for m in following if m.get("role") == "tool"]
                self.assertTrue(tool_replies, "assistant(tool_calls) 缺少 tool 回复")


class TestCompactHistory(unittest.TestCase):
    """验证整体流程的放弃与成功路径（AI 调用以 stub 替换）。"""

    def _stub_ai(self, keys=None, decisions=None, summary="摘要内容"):
        """替换 compaction 内的三次 AI 调用；记录传入的 history 供断言。"""
        self.captured = {}

        async def fake_archive(chat, history):
            self.captured["archive_history"] = history
            return keys or []

        async def fake_decisions(chat, groups, history):
            self.captured["decision_history"] = history
            return decisions

        async def fake_summary(chat, groups, goal, history):
            self.captured["summary_history"] = history
            return summary

        return fake_archive, fake_decisions, fake_summary

    def _patch(self, keys=None, decisions=None, summary="摘要内容"):
        fa, fd, fs = self._stub_ai(keys, decisions, summary)
        self._orig = (compaction._archive, compaction._request_decisions,
                      compaction._request_summary)
        compaction._archive, compaction._request_decisions, compaction._request_summary = fa, fd, fs

    def _unpatch(self):
        (compaction._archive, compaction._request_decisions,
         compaction._request_summary) = self._orig

    def tearDown(self):
        if hasattr(self, "_orig"):
            self._unpatch()

    def test_aborts_when_freed_below_threshold(self):
        chat = FakeChat(_make_messages())
        self._patch(decisions={"keep": [], "delete": [0, 1, 2], "goal": "g"})
        # 阈值设得极高，预检必然失败
        orig = constants.COMPACT_MIN_FREED_RATIO
        constants.COMPACT_MIN_FREED_RATIO = 0.999
        try:
            result = asyncio.run(compaction.compact_history(chat))
        finally:
            constants.COMPACT_MIN_FREED_RATIO = orig
        self.assertIsNone(result)
        # 消息未被修改
        self.assertFalse(any(constants.MSG_SEND_FIELD in m for m in chat.messages))
        # 发出"无需压缩"提示（skipped 字段）
        self.assertTrue(any(e[1].get("skipped") for e in chat.events))

    def test_skip_when_too_few_groups(self):
        """候选分组不足时提示无需压缩，且不修改消息。"""
        chat = FakeChat([
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "只有一个回合"},
        ])
        result = asyncio.run(compaction.compact_history(chat))
        self.assertIsNone(result)
        self.assertTrue(any(e[1].get("skipped") for e in chat.events))

    def test_aborts_when_decision_parse_fails(self):
        chat = FakeChat(_make_messages())
        self._patch(decisions=None)
        result = asyncio.run(compaction.compact_history(chat))
        self.assertIsNone(result)
        self.assertFalse(any(constants.MSG_SEND_FIELD in m for m in chat.messages))

    def test_success_flow(self):
        msgs = _make_messages()
        chat = FakeChat(msgs)
        self._patch(keys=["archive_x"],
                    decisions={"keep": [1], "delete": [0], "goal": "任务"},
                    summary="整体摘要")
        # 阈值置 0，避免小消息量被预检拦截
        orig = constants.COMPACT_MIN_FREED_RATIO
        constants.COMPACT_MIN_FREED_RATIO = 0.0
        try:
            result = asyncio.run(compaction.compact_history(chat))
        finally:
            constants.COMPACT_MIN_FREED_RATIO = orig
        self.assertIsNotNone(result)
        self.assertTrue(chat.saved)
        # 发出整理事件（开始 + 结束）
        event_types = [e[0] for e in chat.events]
        self.assertIn("context_compact_start", event_types)
        self.assertIn("context_compacted", event_types)
        # 末尾追加了一条仅显示的整理记录：_send=False 不发送，user_output 供回显
        record = chat.messages[-1]
        self.assertIs(record.get(constants.MSG_SEND_FIELD), False)
        self.assertIn("user_output", record)
        self.assertEqual(record["user_output"]["parts"][0]["text"], "已完成压缩")
        # 当前回合（整理记录之前的那条 user）未被打标
        self.assertNotIn(constants.MSG_SEND_FIELD, chat.messages[-2])

    def test_reuses_send_list_as_prefix(self):
        """三次 AI 调用共享同一发送列表前缀（复用服务端缓存），且不含 system。"""
        msgs = _make_messages()
        chat = FakeChat(msgs)
        self._patch(keys=["k"], decisions={"keep": [1], "delete": [0], "goal": "g"},
                    summary="摘要")
        orig = constants.COMPACT_MIN_FREED_RATIO
        constants.COMPACT_MIN_FREED_RATIO = 0.0
        try:
            asyncio.run(compaction.compact_history(chat))
        finally:
            constants.COMPACT_MIN_FREED_RATIO = orig
        # 三次调用拿到同一份前缀对象，保证第 2、3 次命中第 1 次建立的缓存
        self.assertIs(self.captured["archive_history"], self.captured["decision_history"])
        self.assertIs(self.captured["archive_history"], self.captured["summary_history"])
        history = self.captured["archive_history"]
        self.assertTrue(all(m.get("role") != "system" for m in history))
        # 前缀起点与主对话发送列表一致
        self.assertEqual(history[0]["content"], "第一个任务")


if __name__ == "__main__":
    unittest.main()
