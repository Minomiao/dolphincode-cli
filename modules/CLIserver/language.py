"""语言设置界面：支持方向键选择显示语言。"""
import shutil

from rich.console import Console

from modules.logger import get_logger
from . import i18n
from . import console_input
from .state import state
from .screen_refresh import clear_screen, create_header_panel, create_footer_panel

log = get_logger("Dolphin.language")
_console = Console()


def language_settings():
    """进入语言设置界面。"""
    cmd = state.cmd
    log.info("进入语言设置")

    def _render():
        languages = i18n.get_supported_languages()
        current = i18n.get_language()
        index = 0
        for i, lang in enumerate(languages):
            if lang["code"] == current:
                index = i
                break

        if not console_input.is_available():
            return _render_text_menu(languages, index)

        console_input.flush()
        while True:
            _render_list(languages, index)
            key = console_input.read_key()
            if key == console_input.KEY_UP:
                index = (index - 1) % len(languages)
            elif key == console_input.KEY_DOWN:
                index = (index + 1) % len(languages)
            elif key == console_input.KEY_ENTER:
                return _apply_language(languages[index])
            elif key == console_input.KEY_ESC or key is None:
                return

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('language'),
                 command_info=f"╰─{cmd.get_command_description('language')}")


def _list_window_size():
    """根据终端高度计算一次显示的条目数（预留头部/底部空间）。"""
    try:
        lines = shutil.get_terminal_size().lines
    except (OSError, ValueError):
        lines = 24
    return max(4, min(18, lines - 12))


def _visible_range(index, total):
    """计算可视窗口 [start, end)，使当前项 index 尽量居中。

    Args:
        index: 当前选中项下标
        total: 语言总数

    Returns:
        (start, end) 窗口起止下标（左闭右开）
    """
    height = _list_window_size()
    if total <= height:
        return 0, total
    start = max(0, min(index - height // 2, total - height))
    return start, start + height


def _render_list(languages, index):
    """渲染语言选择列表（方向键导航）。

    只渲染当前选择附近的可视窗口，避免全部条目超出终端高度时
    视口被推到界面底部。
    """
    clear_screen()
    _console.print()
    _console.print(create_header_panel(
        i18n.t("language.title"),
        i18n.t("language.subtitle"),
    ))
    _console.print()
    total = len(languages)
    start, end = _visible_range(index, total)
    for i in range(start, end):
        lang = languages[i]
        marker = "▶" if i == index else " "
        line = f"{marker} {lang['native']} ({lang['code']})"
        if i == index:
            _console.print(line, style="bold cyan")
        else:
            _console.print(line, style="dim")
    if total > end - start:
        _console.print(f"[dim]({start + 1}-{end}/{total})[/dim]")
    _console.print()
    _console.print(create_footer_panel(i18n.t("language.hint")))


def _render_text_menu(languages, index):
    """无交互控制台（管道/重定向）时的纯文本回退菜单。"""
    cmd = state.cmd

    def _show():
        clear_screen()
        _console.print()
        _console.print(create_header_panel(
            i18n.t("language.title"),
            i18n.t("language.subtitle"),
        ))
        _console.print()
        total = len(languages)
        start, end = _visible_range(index, total)
        for i in range(start, end):
            lang = languages[i]
            marker = "▶" if i == index else " "
            _console.print(f"{marker} {i + 1} - {lang['native']} ({lang['code']})")
        if total > end - start:
            _console.print(f"(显示 {start + 1}-{end}/{total})")
        _console.print()
        _console.print(create_footer_panel(
            f"1-{len(languages)} 选择 | {cmd.get_command_keyword('back')} 返回"
        ))

    while True:
        _show()
        choice = input("\n> ").strip()
        if not choice or choice == cmd.get_command_keyword('back'):
            return
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(languages):
                return _apply_language(languages[idx])
        except ValueError:
            pass
        _console.print(f"[red]{i18n.t('language.invalid')}[/red]")


def _apply_language(lang):
    """应用所选语言并保存配置。"""
    code = lang["code"]
    i18n.init(code)
    state.current_config["language"] = code
    state.config.save_config(state.current_config)
    log.info(f"显示语言已切换: {code}")
    _console.print()
    _console.print(f"[green]{i18n.t('language.switched', name=lang['native'])}[/green]")
    input(i18n.t("main.press_enter"))
    return lang
