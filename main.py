"""Dolphin CLI 入口。

负责项目引导、分步懒加载核心模块、启动进度条显示，以及最终启动主命令循环。
具体的 UI、设置、对话管理、回调等逻辑已拆分到 modules.CLIserver 包中。
"""
import os
import sys
import time
import asyncio

from modules import bootstrap

# 入口文件确定项目根目录（兼容 PyInstaller 打包）
if getattr(sys, 'frozen', False):
    bootstrap.init(os.path.dirname(os.path.abspath(sys.executable)))
else:
    bootstrap.init(os.path.dirname(os.path.abspath(__file__)))

from modules.logger import setup_logger

from colorama import init as _colorama_init
_colorama_init()

from rich.progress import Progress, BarColumn, TextColumn
from rich.console import Console

from modules.bootstrap import constants
from modules.CLIserver import i18n
from modules.CLIserver.state import ui, state
from modules.CLIserver.splash import show_splash, progress_bar
from modules.CLIserver.terminal import exit_screen
from modules.CLIserver.header import print_header, print_conversation_history
from modules.CLIserver.callback import chat_callback
from modules.CLIserver.conversation_ops import open_work_directory
from modules.CLIserver.main_loop import main

_console = Console()
log = setup_logger("Dolphin")

_DEEPSLEEPING = constants.DEEPSLEEPING_TEXT


def _load_config_module():
    """加载配置模块（进度条 20% 阶段）。"""
    from modules.main_server import config
    state.config = config
    # 显式执行配置初始化副作用
    config.init()


def _load_commands_module():
    """加载命令模块（进度条 35% 阶段）。"""
    from modules.CLIserver import commands as cmd
    state.cmd = cmd
    cmd.init()


def _load_core_modules():
    """加载对话、屏幕刷新、备份管理及 OpenAI 等核心重模块（进度条 50% 阶段）。"""
    from openai import AuthenticationError, RateLimitError, APIConnectionError, APIError
    from modules.chater import chat, conversation_loader
    from modules.chater.conversation_loader import format_user_output_line
    from modules.CLIserver import screen_refresh
    from modules.functions import backup_manager
    from modules.functions import powershell_manager

    state.chat = chat
    state.conversation_loader = conversation_loader
    state.format_user_output_line = format_user_output_line
    state.screen_refresh = screen_refresh
    state.backup_manager = backup_manager
    state.AuthenticationError = AuthenticationError
    state.RateLimitError = RateLimitError
    state.APIConnectionError = APIConnectionError
    state.APIError = APIError

    # 显式执行 PowerShell 模块初始化副作用
    powershell_manager.init()


def _startup():
    """执行启动流程：显示 splash、分步加载模块、创建 chat 实例。"""
    show_splash()

    progress_bar(5, _DEEPSLEEPING[:1])
    time.sleep(0.1)

    # 20%：加载配置模块
    _load_config_module()
    state.current_config = state.config.load_config()
    i18n.init(state.current_config.get('language', 'zh-CN'))
    state.show_thinking = state.current_config.get('show_thinking', False)
    state.effort_level = state.current_config.get('effort_level', 'fine')
    if 'effort_level' not in state.current_config:
        state.current_config['effort_level'] = 'fine'
        state.config.save_config(state.current_config)
    progress_bar(20, _DEEPSLEEPING[:3])
    time.sleep(0.1)

    # 35%：加载命令模块并校验
    _load_commands_module()
    progress_bar(35, _DEEPSLEEPING[:7])
    time.sleep(0.1)

    deprecation_warning = state.config.check_model_deprecation(
        state.current_config.get('model', constants.DEFAULT_MODEL))
    if deprecation_warning:
        log.warning(deprecation_warning)

    workplace_dir = state.current_config.get('work_directory', 'workplace')
    # 相对路径基于项目根目录解析为绝对路径
    if not os.path.isabs(workplace_dir):
        workplace_dir = os.path.join(bootstrap.PROJECT_ROOT, workplace_dir)
    if not os.path.exists(workplace_dir):
        workplace_dir = os.path.join(bootstrap.PROJECT_ROOT, 'workplace')
        log.warning(f"工作目录不存在，回退到默认目录: {workplace_dir}")
        state.current_config['work_directory'] = workplace_dir
        state.config.save_config(state.current_config)
    if not os.path.exists(workplace_dir):
        os.makedirs(workplace_dir)
        log.info(f"创建工作目录: {workplace_dir}")
    progress_bar(50, _DEEPSLEEPING[:11])

    # 50%：加载核心对话、屏幕刷新、备份管理及 OpenAI 等较重模块
    _load_core_modules()

    time.sleep(0.1)

    state.chat_instance = state.chat.DolphinChat(
        model=state.current_config.get('model', constants.DEFAULT_MODEL),
        max_tokens=state.current_config.get('max_tokens', 18000),
        callback=chat_callback
    )
    state.chat_instance.effort_level = state.effort_level
    progress_bar(85, _DEEPSLEEPING[:17])
    time.sleep(0.1)

    state.current_conversation = "main"
    state.current_dir_id = None
    state.current_conv_id = None

    log.info("Dolphin 启动")
    log.info(
        f"当前配置: model={state.current_config.get('model')}, "
        f"language={state.current_config.get('language')}, "
        f"max_tokens={state.current_config.get('max_tokens', 18000)}, "
        f"effort={state.effort_level}, "
        f"conversation={state.current_conversation}, "
        f"work_directory={workplace_dir}"
    )
    progress_bar(100, _DEEPSLEEPING)
    time.sleep(0.3)
    state.screen_refresh.clear_screen()

    print_header()

    open_work_directory(workplace_dir, silent=True)

    if state.chat_instance.messages:
        print_conversation_history()


def _exit_save():
    """退出兜底：将内存中未落盘内容（含流式缓冲残留）同步写盘。"""
    chat = state.chat_instance
    if not chat or not (state.current_dir_id and state.current_conv_id):
        return
    try:
        chat.save_on_exit(state.current_dir_id, state.current_conv_id)
    except Exception as e:
        log.warning(f"退出保存失败: {e}")


if __name__ == "__main__":
    try:
        _startup()
        asyncio.run(main())
    finally:
        _exit_save()
        exit_screen()
