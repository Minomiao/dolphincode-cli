"""
统一的终端清屏/重绘模块。
将项目中散布的 os.system('cls') + _print_header() + _print_conversation_history()
模式收拢为单次调用，支持 清屏 -> 头 -> 消息 -> 对话历史 的连贯渲染。
"""

import os
from typing import Callable, Optional
from colorama import Fore, Style
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from modules.logger import get_logger

log = get_logger("Dolphin.screen_refresh")

_console = Console()


def clear_screen():
    """跨平台清屏"""
    os.system('cls' if os.name == 'nt' else 'clear')


def refresh(header_fn, history_fn=None, message=None, show_history=True):
    """
    统一终端重绘。

    参数:
        header_fn:   callable, 无参, 负责绘制页面头部 (如 _print_header)
        history_fn:  callable, 无参, 负责绘制对话历史 (如 _print_conversation_history)
        message:     str | None, 在头部之后、历史之前印出的通告消息
        show_history: bool, 是否调用 history_fn
    """
    clear_screen()
    header_fn()
    if message:
        print(message)
    if show_history and history_fn:
        history_fn()


def enter_screen(render_fn: Callable, message: Optional[str] = None,
                 command_input: Optional[str] = None,
                 command_info: Optional[str] = None):
    """
    进入独立界面的统一入口。
    清屏 -> 调用渲染函数 -> 退出时返回主界面。

    参数:
        render_fn:     callable, 负责渲染界面内容，可返回任意值
        message:       str | None, 退出时显示的消息
        command_input: str | None, 触发该界面的命令文本（如 '/help'）
        command_info:  str | None, 命令的描述信息

    返回:
        render_fn 的返回值
    """
    from .header import print_header, print_conversation_history

    clear_screen()
    result = render_fn()
    refresh(print_header, print_conversation_history, message)
    if command_input:
        print()
        print(f"{Fore.WHITE}>{Fore.CYAN}{command_input}{Style.RESET_ALL}")
    if command_info:
        print(f"{Style.DIM}{command_info}{Style.RESET_ALL}")
    return result


def create_header_panel(title: str, subtitle: Optional[str] = None) -> Panel:
    """创建带标题的面板头部。

    Args:
        title: 标题文本
        subtitle: 可选的副标题

    Returns:
        Rich Panel 对象
    """
    content = Text(title, style="bold cyan")
    if subtitle:
        content.append(f"\n{subtitle}", style="dim")
    return Panel(content, border_style="cyan")


def create_footer_panel(hint: str) -> Panel:
    """创建底部提示面板。

    Args:
        hint: 提示文本

    Returns:
        Rich Panel 对象
    """
    return Panel(Text(hint, style="dim"), border_style="dim")
