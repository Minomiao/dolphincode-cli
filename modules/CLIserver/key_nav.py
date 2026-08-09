"""方向键列表导航公共组件。

提供统一的列表选择交互：上下键移动、回车确认、Esc 返回，
以及无交互控制台（管道/重定向）时的纯文本数字回退菜单。
供语言、模型、设置、思考深度、技能管理等界面复用。
"""
import shutil

from rich.console import Console

from modules.logger import get_logger
from . import console_input
from . import i18n
from .state import state
from .screen_refresh import clear_screen, create_header_panel, create_footer_panel

log = get_logger("Dolphin.key_nav")
_console = Console()


def list_window_size():
    """根据终端高度计算一次显示的条目数（预留头部/底部空间）。"""
    try:
        lines = shutil.get_terminal_size().lines
    except (OSError, ValueError):
        lines = 24
    return max(4, min(18, lines - 12))


def visible_range(index, total, line_height=1):
    """计算可视窗口 [start, end)，使当前项 index 尽量居中。

    Args:
        index: 当前选中项下标
        total: 条目总数
        line_height: 每个条目占用的终端行数

    Returns:
        (start, end) 窗口起止下标（左闭右开）
    """
    height = list_window_size() // max(1, line_height)
    if total <= height:
        return 0, total
    start = max(0, min(index - height // 2, total - height))
    return start, start + height


def navigate(title, subtitle, options, label_fn, on_enter, hint,
             initial=0, extra_key=None, line_height=1):
    """方向键列表导航循环。

    Args:
        title: 头部标题
        subtitle: 头部副标题
        options: 选项列表（可为空，为空直接返回 None）
        label_fn: callable(option, index) -> 显示文本（支持换行分行）
        on_enter: callable(option, index) -> bool；回车时调用，返回 True 退出循环
        hint: 底部提示
        initial: 初始选中下标
        extra_key: callable(key, option, index) -> bool；处理额外字符键，
            返回 True 表示已处理并继续循环
        line_height: 每个条目占用的终端行数（多行条目用于窗口滚动）

    Returns:
        回车确认退出的选中下标；Esc/返回时为 None
    """
    if not options:
        return None
    if not console_input.is_available():
        return _number_menu(title, subtitle, options, label_fn, on_enter,
                            hint, initial, line_height)

    index = initial % len(options)
    console_input.flush()
    while True:
        clear_screen()
        _console.print()
        _console.print(create_header_panel(title, subtitle))
        _console.print()
        total = len(options)
        start, end = visible_range(index, total, line_height)
        for i in range(start, end):
            option = options[i]
            marker = "▶" if i == index else " "
            lines = label_fn(option, i).split("\n")
            first = f"{marker} {lines[0]}" if lines else marker
            rendered = [first] + [f"   {line}" for line in lines[1:]]
            for line in rendered:
                if i == index:
                    _console.print(line, style="bold cyan")
                else:
                    # 未选中行明确指定蓝灰色，避免纯 dim（未指定颜色）在
                    # 部分终端下渲染为灰色且各行业色不一致
                    _console.print(line, style="dim cyan")
        if total > end - start:
            _console.print(f"[dim]({start + 1}-{end}/{total})[/dim]")
        _console.print()
        _console.print(create_footer_panel(hint))

        key = console_input.read_key()
        if key == console_input.KEY_UP:
            index = (index - 1) % total
        elif key == console_input.KEY_DOWN:
            index = (index + 1) % total
        elif key == console_input.KEY_ENTER:
            if on_enter(options[index], index):
                return index
        elif key == console_input.KEY_ESC or key is None:
            return None
        elif extra_key is not None and key is not None:
            if extra_key(key, options[index], index):
                continue


def _number_menu(title, subtitle, options, label_fn, on_enter, hint,
                 initial=0, line_height=1):
    """无交互控制台（管道/重定向）时的纯文本数字回退菜单。"""
    cmd = state.cmd
    index = initial % len(options)

    def _show():
        clear_screen()
        _console.print()
        _console.print(create_header_panel(title, subtitle))
        _console.print()
        total = len(options)
        start, end = visible_range(index, total, line_height)
        for i in range(start, end):
            option = options[i]
            marker = "▶" if i == index else " "
            lines = label_fn(option, i).split("\n")
            first = f"{marker} {i + 1} - {lines[0]}" if lines else f"{marker} {i + 1} -"
            rendered = [first] + [f"   {line}" for line in lines[1:]]
            for line in rendered:
                _console.print(line)
        if total > end - start:
            _console.print(f"(显示 {start + 1}-{end}/{total})")
        _console.print()
        _console.print(create_footer_panel(
            f"1-{total} 选择 | {cmd.get_command_keyword('back')} 返回 | {hint}"
        ))

    while True:
        _show()
        choice = input("\n> ").strip()
        if not choice or choice == cmd.get_command_keyword('back'):
            return None
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                if on_enter(options[idx], idx):
                    return idx
                continue
        except ValueError:
            pass
        _console.print(f"[red]{i18n.t('keynav.invalid_input')}[/red]")
