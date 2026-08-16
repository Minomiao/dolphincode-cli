"""CLI 全局运行时状态。

集中管理 UI 状态、应用业务状态和懒加载的模块引用，
避免在 main.py 中散布大量全局变量。
"""


class UIState:
    """封装 UI 运行时状态。"""

    def __init__(self):
        self.using_alt_screen = False
        self.thinking_start_time = 0.0
        self.turn_first_output = True
        self.progress = None
        self._tool_pending = False
        self._spinner_task = None
        self._pending_context_usage = None  # 暂存的 token 用量，在回显中显示
        self._indented_after_thinking = False  # 思考结束后进入缩进模式
        self.at_line_start = True  # 流式输出后光标是否位于行首（用于后续换行）


class AppState:
    """封装应用业务状态。

    懒加载的模块引用由 main.py 在启动流程中逐步填充，
    各 CLI 子模块通过 state.xxx 访问。
    """

    def __init__(self):
        self.current_config = None
        self.chat_instance = None
        self.current_conversation = None
        self.current_dir_id = None
        self.current_conv_id = None
        self.show_thinking = False
        self.effort_level = "fine"

        # 懒加载的模块引用（由 main.py 在启动进度条阶段填充）
        self.config = None
        self.cmd = None
        self.chat = None
        self.conversation_loader = None
        self.format_user_output_line = None
        self.screen_refresh = None
        self.backup_manager = None
        self.AuthenticationError = None
        self.RateLimitError = None
        self.APIConnectionError = None
        self.APIError = None


ui = UIState()
state = AppState()
