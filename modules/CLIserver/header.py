"""页面头部与对话历史渲染。"""
from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from rich import box

from modules.bootstrap import constants
from . import i18n
from .state import state

_DOLPHIN_ART = constants.DOLPHIN_ART


def print_header():
    """打印主界面头部。"""
    cmd = state.cmd
    config = state.config
    deprecation_warning = config.check_model_deprecation(
        state.current_config.get('model', constants.DEFAULT_MODEL))
    work_dir = state.current_config.get('work_directory', 'workplace')

    dolphin = Text(_DOLPHIN_ART, style="bright_blue")

    info = Text()
    if deprecation_warning:
        info.append(f"{deprecation_warning}\n", style="yellow")
    info.append(i18n.t("header.help_hint", command=cmd.get_command('help')) + "\n", style="dim")
    info.append(i18n.t("header.work_dir"), style="dim")
    info.append(work_dir, style="white")

    panel = Panel(
        Group(dolphin, "", info),
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )
    from .splash import _console
    _console.print(panel)


def print_conversation_history():
    """打印对话历史。"""
    conversation_loader = state.conversation_loader
    output = conversation_loader.format_conversation_history(
        state.chat_instance.messages, state.show_thinking)
    if output:
        print(output)
