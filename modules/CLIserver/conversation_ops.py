"""对话管理操作界面：打开工作目录、新建/加载/列出对话。

业务逻辑委托 modules.core.services.conversation_service，
本模块只负责交互输入与界面渲染。
"""
import os

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from modules.bootstrap import constants
from modules.logger import get_logger
from modules.core.services import conversation_service
from . import i18n
from .state import state
from .screen_refresh import create_header_panel, create_footer_panel

log = get_logger("Dolphin.conversation_ops")
_console = Console()


def open_work_directory(path=None, silent=False):
    """打开/切换工作目录。"""
    if not path:
        cur = state.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
        print(f"\n当前工作目录: {cur}")
        path = input("输入要打开的工作目录: ")
        if not path:
            print("取消操作")
            return

    abs_path = conversation_service.resolve_work_directory(path)
    if not os.path.exists(abs_path):
        _console.print(f"[yellow]目录不存在: {path}[/yellow]")
        choice = input("是否创建该目录? (y/n): ").strip().lower()
        if choice not in ('y', 'yes'):
            print("取消操作")
            return

    old_work_directory = state.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    if abs_path != old_work_directory:
        print("工作目录已更改，正在重新加载技能模块...")

    result = conversation_service.open_work_directory(state, path, create_if_missing=True)

    if not result.get('success'):
        log.warning(f"打开工作目录失败: {result.get('error')}")
        _console.print(f"[red]打开工作目录失败: {result.get('error')}[/red]")
        return

    if result.get('created_dir'):
        _console.print(f"[green]已创建: {abs_path}[/green]")
    if result.get('skills_reloaded'):
        print("技能模块已重新加载")

    from .header import print_header, print_conversation_history

    if result.get('action') == 'loaded':
        if not silent:
            state.screen_refresh.refresh(
                print_header, print_conversation_history,
                f"已自动加载对话: {result.get('conv_name')}")
    else:
        if not silent:
            state.screen_refresh.refresh(
                print_header, print_conversation_history,
                f"已创建新对话: {result.get('conv_name')}", show_history=False)


def new_conversation(new_name):
    """新建对话。"""
    if not new_name:
        new_name = input("请输入新对话名称: ")
    if not new_name:
        return

    result = conversation_service.create_conversation(state, new_name)
    if not result.get('success'):
        if result.get('error') == 'duplicate':
            print(f"对话 '{new_name}' 已存在，请使用其他名称（加载已有对话请使用 {state.cmd.get_command('load')}）")
        return

    from .header import print_header, print_conversation_history
    state.screen_refresh.refresh(print_header, print_conversation_history,
                                 f"已切换到新对话: {new_name}", show_history=False)


def load_conversation(load_name):
    """加载旧对话；无名称时进入上下键选择界面。"""
    if not load_name:
        select_conversation('load')
        return

    result = conversation_service.activate_conversation(state, load_name)
    if not result.get('success'):
        if result.get('error') == 'not_found':
            print(i18n.t("conv.not_found", name=load_name))
        return

    from .header import print_header, print_conversation_history
    state.screen_refresh.refresh(print_header, print_conversation_history,
                                 i18n.t("conv.loaded", name=load_name))


def select_conversation(command_key='list'):
    """对话选择界面：上下键浏览所有对话，Enter 加载，Esc 返回。

    Args:
        command_key: 触发该界面的命令标识（默认 'list'），用于退出后的命令回显
    """
    cmd = state.cmd
    log.info(f"进入对话选择界面（来源命令: {command_key}）")

    def _render():
        work_dir = state.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
        dpc_convs = conversation_service.list_conversations(state)
        log.info(f"对话选择界面（工作目录: {work_dir}），共 {len(dpc_convs)} 个对话")

        if not dpc_convs:
            _console.print()
            _console.print(create_header_panel(i18n.t("conv.title"),
                                               f"{i18n.t('header.work_dir')}{work_dir}"))
            _console.print()
            _console.print(Panel(Text(i18n.t("conv.no_conversations"), style="yellow"),
                                 border_style="yellow"))
            _console.print()
            _console.print(create_footer_panel(i18n.t("display.back_hint")))
            input()
            return

        current_id = state.current_conv_id
        initial = 0
        for i, conv in enumerate(dpc_convs):
            if conv["id"] == current_id:
                initial = i
                break

        def _label(conv, i):
            marker = "✓" if conv["id"] == current_id else ""
            line = conv["name"]
            if marker:
                line += f"  {marker}"
            return line

        def _on_enter(conv, i):
            result = conversation_service.activate_conversation_by_id(
                state, conv['id'], conv['name'])
            if result.get('success'):
                _console.print(f"[green]{i18n.t('conv.loaded', name=conv['name'])}[/green]")
            input(i18n.t("main.press_enter"))
            return True

        from .key_nav import navigate
        navigate(i18n.t("conv.title"),
                 f"{i18n.t('header.work_dir')}{work_dir}",
                 dpc_convs, _label, _on_enter,
                 i18n.t("conv.hint"),
                 initial=initial)

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command(command_key),
                 command_info=f"╰─{cmd.get_command_description(command_key)}")
