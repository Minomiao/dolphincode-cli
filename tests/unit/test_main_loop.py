"""主命令循环（main_loop）单元测试：分派表完整性、命令解析与分发行为。"""
import unittest
from unittest.mock import patch

from modules.CLIserver import main_loop
from modules.CLIserver.commands import get_command_keyword
from modules.CLIserver.main_loop import _QUIT, _parse_command, _cmd_quit, _cmd_back
from modules.CLIserver.state import state, ui

# 默认命令名（与 commands.py 默认表对应）
COMMAND_NAMES = [
    "help", "clear", "model", "set", "open", "new", "list", "load",
    "back", "quit", "tools", "skills", "changes", "showthinking",
    "effort", "toggle", "language",
]


class TestCommandTable(unittest.TestCase):
    """命令分派表完整性。"""

    def test_covers_all_default_commands(self):
        for name in COMMAND_NAMES:
            keyword = get_command_keyword(name)
            self.assertIn(keyword, main_loop._COMMAND_TABLE, f"缺少命令 {name}")

    def test_all_handlers_callable(self):
        for keyword, handler in main_loop._COMMAND_TABLE.items():
            self.assertTrue(callable(handler), f"{keyword} 的处理器不可调用")

    def test_keywords_non_empty(self):
        for keyword in main_loop._COMMAND_TABLE:
            self.assertTrue(keyword, "关键词不能为空")

    def test_quit_handler_returns_quit(self):
        self.assertIs(_cmd_quit(None), _QUIT)

    def test_back_handler_returns_none(self):
        self.assertIsNone(_cmd_back(None))


class TestParseCommand(unittest.TestCase):
    """命令解析逻辑。"""

    def test_non_command_returns_none(self):
        self.assertIsNone(_parse_command("hello world", "/"))

    def test_bare_keyword(self):
        self.assertEqual(_parse_command("/help", "/"), ("help", ""))

    def test_keyword_with_args(self):
        self.assertEqual(_parse_command("/open D:/codes", "/"), ("open", "D:/codes"))

    def test_multiple_spaces_between_keyword_and_args(self):
        self.assertEqual(_parse_command("/effort   high", "/"), ("effort", "high"))

    def test_case_insensitive(self):
        self.assertEqual(_parse_command("/HELP", "/"), ("help", ""))

    def test_custom_prefix(self):
        self.assertEqual(_parse_command("!help", "!"), ("help", ""))


class TestMainLoopDispatch(unittest.IsolatedAsyncioTestCase):
    """主循环分发行为（mock input 驱动）。"""

    def setUp(self):
        state.current_config = {"command_prefix": "/"}

    async def test_unknown_command_prints_and_continues(self):
        with patch("builtins.input", side_effect=["/nosuch", EOFError]), \
                patch("builtins.print") as fake_print:
            await main_loop.main()
        fake_print.assert_any_call(
            main_loop.i18n.t("main.unknown_command", keyword="nosuch"))

    async def test_quit_exits_immediately(self):
        with patch("builtins.input", side_effect=["/quit"]) as fake_input, \
                patch("builtins.print") as fake_print:
            await main_loop.main()
        fake_input.assert_called_once()
        fake_print.assert_any_call(main_loop.i18n.t("main.goodbye"))

    async def test_back_continues_loop(self):
        with patch("builtins.input", side_effect=["/back", EOFError]), \
                patch("builtins.print"):
            await main_loop.main()
        # back 无操作后继续循环，EOFError 正常退出即通过

    async def test_help_forwards_to_display(self):
        with patch("builtins.input", side_effect=["/help", EOFError]), \
                patch("modules.CLIserver.main_loop.show_help") as fake_show_help:
            await main_loop.main()
        fake_show_help.assert_called_once_with()

    async def test_changes_forwards_via_lazy_import(self):
        with patch("builtins.input", side_effect=["/changes", EOFError]), \
                patch("modules.CLIserver.changes.handle_pending_changes") as fake:
            await main_loop.main()
        fake.assert_called_once_with()

    async def test_showthinking_no_args_prints_status(self):
        state.show_thinking = True
        with patch("builtins.input", side_effect=["/showthinking", EOFError]), \
                patch("builtins.print") as fake_print:
            await main_loop.main()
        fake_print.assert_any_call(
            main_loop.i18n.t("main.thinking_current", status=main_loop.i18n.t("main.on")))

    async def test_effort_no_args_forwards_to_settings(self):
        with patch("builtins.input", side_effect=["/effort", EOFError]), \
                patch("modules.CLIserver.main_loop.effort_settings") as fake:
            await main_loop.main()
        fake.assert_called_once_with()


class TestInterruptHandling(unittest.IsolatedAsyncioTestCase):
    """Ctrl+C 分流行为：生成中取消回提示符，空闲时直接退出。"""

    def setUp(self):
        state.current_config = {
            "command_prefix": "/",
            "api_key": "test-key",
            "model": "test-model",
        }
        ui.generating = False

    async def test_cancelled_during_generation_seals_and_continues(self):
        """生成中 GenerationCancelled → 封口保留消息、清 spinner、无提示继续。"""
        from modules.core import GenerationCancelled

        async def fake_chat_stream(_input, images=None):
            raise GenerationCancelled()

        with patch("builtins.input", side_effect=["hello", EOFError]), \
                patch("builtins.print") as fake_print, \
                patch("modules.CLIserver.main_loop.clear_tool_pending") as fake_clear, \
                patch.object(state, "chat_instance") as fake_instance:
            fake_instance.chat_stream = fake_chat_stream
            await main_loop.main()

        fake_instance.seal_interrupted_turn.assert_called_once_with()
        fake_clear.assert_called()
        # 无额外提示：不打印中断文案
        interrupted_text = main_loop.i18n.t("main.interrupted")
        for call in fake_print.call_args_list:
            self.assertNotIn(interrupted_text, str(call))
        # 循环继续：后续 EOFError 正常退出，且 ui.generating 已复位
        self.assertFalse(ui.generating)

    async def test_cancelled_mid_line_writes_newline_for_blank_separator(self):
        """行中中断：补换行收尾，使新提示符前形成一整行空行。"""
        from modules.core import GenerationCancelled

        async def fake_chat_stream(_input, images=None):
            raise GenerationCancelled()

        ui.at_line_start = False
        try:
            with patch("builtins.input", side_effect=["hello", EOFError]), \
                    patch("sys.stdout.write") as fake_write, \
                    patch.object(state, "chat_instance") as fake_instance:
                fake_instance.chat_stream = fake_chat_stream
                await main_loop.main()
            fake_write.assert_any_call("\n")
            self.assertTrue(ui.at_line_start)
        finally:
            ui.at_line_start = True

    async def test_generating_flag_reset_on_api_error(self):
        """API 错误路径后 generating 标志必须复位为 False。"""

        class FakeAPIError(Exception):
            pass

        async def fake_chat_stream(_input, images=None):
            raise FakeAPIError("boom")

        with patch("builtins.input", side_effect=["hello", EOFError]), \
                patch.object(state, "APIError", FakeAPIError), \
                patch.object(state, "AuthenticationError", FakeAPIError), \
                patch.object(state, "RateLimitError", FakeAPIError), \
                patch.object(state, "APIConnectionError", FakeAPIError), \
                patch("modules.CLIserver.main_loop.rollback_last_message"), \
                patch("modules.CLIserver.main_loop.clear_tool_pending"), \
                patch.object(state, "chat_instance") as fake_instance:
            fake_instance.chat_stream = fake_chat_stream
            await main_loop.main()

        self.assertFalse(ui.generating)

    async def test_keyboard_interrupt_at_prompt_exits(self):
        """提示符下 KeyboardInterrupt → 打印 goodbye 并退出。"""
        with patch("builtins.input", side_effect=[KeyboardInterrupt]), \
                patch("builtins.print") as fake_print:
            await main_loop.main()
        fake_print.assert_any_call(f"\n{main_loop.i18n.t('main.goodbye')}")

    def test_sigint_handler_dispatch(self):
        """handler 分流：生成中调 request_cancel 传回后端，否则抛 KeyboardInterrupt。"""
        # 生成中：取消消息传回后端（chat_instance.request_cancel 被调用）
        with patch.object(state, "chat_instance") as fake_instance:
            ui.generating = True
            try:
                main_loop._sigint_handler(2, None)
                fake_instance.request_cancel.assert_called_once_with()
            finally:
                ui.generating = False

        # 空闲：抛 KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            main_loop._sigint_handler(2, None)

    def test_sigint_handler_without_chat_instance_raises(self):
        """生成中但 chat_instance 未就绪：退化为 KeyboardInterrupt。"""
        with patch.object(state, "chat_instance", None):
            ui.generating = True
            try:
                with self.assertRaises(KeyboardInterrupt):
                    main_loop._sigint_handler(2, None)
            finally:
                ui.generating = False


if __name__ == "__main__":
    unittest.main()
