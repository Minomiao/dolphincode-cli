"""对话管理操作：打开工作目录、新建/加载/列出对话。"""
import os

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from modules import bootstrap
from modules.logger import get_logger
from . import i18n
from .state import state
from .screen_refresh import create_header_panel, create_footer_panel

log = get_logger("Dolphin.conversation_ops")
_console = Console()


def open_work_directory(path=None, silent=False):
    """打开/切换工作目录。"""
    cmd = state.cmd
    config = state.config
    conversation_loader = state.conversation_loader
    screen_refresh = state.screen_refresh

    if not path:
        cur = state.current_config.get('work_directory', 'workplace')
        print(f"\n当前工作目录: {cur}")
        path = input("输入要打开的工作目录: ")
        if not path:
            print("取消操作")
            return

    # 相对路径基于项目根目录解析为绝对路径
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(bootstrap.PROJECT_ROOT, path))

    # 校验目录存在性：不存在时提示是否自动创建（silent 模式直接创建，幂等）
    if not os.path.exists(path):
        if silent:
            try:
                os.makedirs(path, exist_ok=True)
                log.info(f"创建工作目录: {path}")
            except Exception as e:
                log.warning(f"创建工作目录失败: {e}")
                return
        else:
            _console.print(f"[yellow]目录不存在: {path}[/yellow]")
            choice = input("是否创建该目录? (y/n): ").strip().lower()
            if choice not in ('y', 'yes'):
                print("取消操作")
                return
            try:
                os.makedirs(path, exist_ok=True)
                _console.print(f"[green]已创建: {path}[/green]")
            except Exception as e:
                log.error(f"创建工作目录失败: {e}")
                _console.print(f"[red]创建工作目录失败: {e}[/red]")
                return

    old_work_directory = state.current_config.get('work_directory', 'workplace')
    if path != old_work_directory:
        state.current_config['work_directory'] = path
        config.save_config(state.current_config)
        log.info(f"工作目录已更改: {old_work_directory} -> {path}")

    if path != old_work_directory:
        print(f"工作目录已更改，正在重新加载技能模块...")
        # 复用同一单例重载技能，避免 importlib.reload 造成模块/单例分裂
        sm = state.chat_instance.skill_mgr
        sm.reload_skills()
        sm.set_work_dir(path)
        if state.chat_instance.plugin_loader:
            state.chat_instance.plugin_loader.set_work_dir(path)
        state.chat_instance._update_tools()
        print("技能模块已重新加载")

    from modules.chater import dpc_manager

    if state.chat_instance.messages and state.current_dir_id and state.current_conv_id:
        state.chat_instance.save_conversation(state.current_dir_id, state.current_conv_id)
        log.info(f"自动保存旧对话: {state.current_conversation}")

    dir_id = dpc_manager.ensure_dir_id(path)
    conv_id, conv_name = dpc_manager.get_current(path)

    from .header import print_header, print_conversation_history

    if conv_id and conv_name:
        result = conversation_loader.load_and_activate(
            state.chat_instance, dir_id, conv_id, conv_name, path)
        if result:
            state.current_conversation = result['conv_name']
            state.current_dir_id = result['dir_id']
            state.current_conv_id = result['conv_id']
            state.chat_instance.set_save_target(result['dir_id'], result['conv_id'])
            if not silent:
                screen_refresh.refresh(print_header, print_conversation_history, f"已自动加载对话: {conv_name}")
            return

    if conv_id:
        log.warning(f".dpc 指向的对话不存在，将创建新对话")

    state.chat_instance.clear_history()

    conv_name = os.path.basename(path.rstrip('/\\'))
    if not conv_name:
        conv_name = "default"
    existing_names = [c["name"] for c in dpc_manager.get_conversations(path)]
    base_name = conv_name
    counter = 1
    while conv_name in existing_names:
        conv_name = f"{base_name}_{counter}"
        counter += 1

    from modules.chater import conversation
    dir_id, new_conv_id = conversation.init_conversation(dir_id, None, conv_name, path)
    state.current_conversation = conv_name
    state.current_dir_id = dir_id
    state.current_conv_id = new_conv_id
    state.chat_instance.set_save_target(dir_id, new_conv_id)
    log.info(f"为工作目录创建新对话: {conv_name} ({new_conv_id})")
    if not silent:
        screen_refresh.refresh(print_header, print_conversation_history, f"已创建新对话: {conv_name}", show_history=False)


def new_conversation(new_name):
    """新建对话。"""
    cmd = state.cmd
    config = state.config
    conversation_loader = state.conversation_loader
    screen_refresh = state.screen_refresh

    if not new_name:
        new_name = input("请输入新对话名称: ")
    if not new_name:
        return

    # 检查是否已存在同名对话
    from modules.chater import dpc_manager
    work_dir = state.current_config.get('work_directory', 'workplace')
    existing_conv_id = dpc_manager.get_id_by_name(work_dir, new_name)
    if existing_conv_id:
        print(f"对话 '{new_name}' 已存在，请使用其他名称（加载已有对话请使用 {cmd.get_command('load')}）")
        log.warning(f"新建对话被阻止：同名对话已存在 '{new_name}' ({existing_conv_id})")
        return

    # 自动保存当前对话
    if state.chat_instance.messages and state.current_dir_id and state.current_conv_id:
        state.chat_instance.save_conversation(state.current_dir_id, state.current_conv_id)
        log.info(f"自动保存当前对话: {state.current_conversation}")

    state.chat_instance.clear_history()
    from modules.chater import conversation
    dir_id, conv_id = conversation.init_conversation(None, None, new_name, work_dir)
    state.current_conversation = new_name
    state.current_dir_id = dir_id
    state.current_conv_id = conv_id
    state.chat_instance.set_save_target(dir_id, conv_id)
    log.info(f"切换到新对话: {new_name} ({conv_id})")

    from .header import print_header, print_conversation_history
    screen_refresh.refresh(print_header, print_conversation_history, f"已切换到新对话: {new_name}", show_history=False)


def _load_and_activate(work_dir, conv_id, conv_name):
    """加载指定对话并更新全局状态（不刷新界面）。

    Args:
        work_dir: 工作目录
        conv_id: 对话 ID
        conv_name: 对话名称

    Returns:
        bool: 是否加载成功
    """
    from modules.chater import dpc_manager
    conversation_loader = state.conversation_loader
    dir_id = dpc_manager.ensure_dir_id(work_dir)
    result = conversation_loader.load_and_activate(
        state.chat_instance, dir_id, conv_id, conv_name, work_dir)
    if not result:
        return False
    state.current_conversation = result['conv_name']
    state.current_dir_id = result['dir_id']
    state.current_conv_id = result['conv_id']
    state.chat_instance.set_save_target(result['dir_id'], result['conv_id'])
    return True


def load_conversation(load_name):
    """加载旧对话；无名称时进入上下键选择界面。"""
    if not load_name:
        select_conversation('load')
        return

    from modules.chater import dpc_manager
    work_dir = state.current_config.get('work_directory', 'workplace')
    dir_id = dpc_manager.ensure_dir_id(work_dir)
    load_conv_id = dpc_manager.get_id_by_name(work_dir, load_name)
    if not load_conv_id:
        log.warning(f"对话不存在: {load_name}")
        print(i18n.t("conv.not_found", name=load_name))
        return

    if not _load_and_activate(work_dir, load_conv_id, load_name):
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
        from modules.chater import dpc_manager
        from .key_nav import navigate

        work_dir = state.current_config.get('work_directory', 'workplace')
        dpc_convs = dpc_manager.get_conversations(work_dir)
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
            if _load_and_activate(work_dir, conv["id"], conv["name"]):
                _console.print(f"[green]{i18n.t('conv.loaded', name=conv['name'])}[/green]")
            input(i18n.t("main.press_enter"))
            return True

        navigate(i18n.t("conv.title"),
                 f"{i18n.t('header.work_dir')}{work_dir}",
                 dpc_convs, _label, _on_enter,
                 i18n.t("conv.hint"),
                 initial=initial)

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command(command_key),
                 command_info=f"╰─{cmd.get_command_description(command_key)}")
