"""设置模式、模型设置和工具切换界面。"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from modules.logger import get_logger
from modules.bootstrap import constants
from . import i18n
from .state import state
from .screen_refresh import create_header_panel, create_footer_panel

log = get_logger("Dolphin.settings")
_console = Console()


def _rebuild_client_and_chat():
    """根据当前配置重建 OpenAI 客户端和 chat 实例。"""
    config = state.config
    chat = state.chat

    # 保留旧实例的消息，避免对话历史丢失
    old_messages = []
    if state.chat_instance is not None:
        old_messages = state.chat_instance.messages

    state.chat_instance = chat.DolphinChat(
        model=state.current_config.get('model'),
        max_tokens=state.current_config.get('max_tokens', 18000),
        callback=_chat_callback_proxy
    )
    state.chat_instance.effort_level = state.effort_level
    state.chat_instance.messages = old_messages
    # 恢复保存目标，避免重建后自动保存失效导致退出丢失本轮消息
    if state.current_dir_id and state.current_conv_id:
        state.chat_instance.set_save_target(state.current_dir_id, state.current_conv_id)
    log.info("客户端已更新")
    print("客户端已更新")


def _chat_callback_proxy(event_type, data):
    """延迟解析的回调代理，避免循环导入。"""
    from .callback import chat_callback
    return chat_callback(event_type, data)


def settings_mode():
    """进入设置界面（上下键选择配置项）。"""
    cmd = state.cmd
    config = state.config
    log.info("进入设置模式")

    def _run_token():
        """修改最大 Token 数。"""
        current_max_tokens = state.current_config.get('max_tokens', 18000)
        _console.print()
        _console.print(Panel(Text(i18n.t("settings.max_tokens_panel", current=current_max_tokens)), title=i18n.t("settings.max_tokens"), border_style="cyan"))
        new_value = input(i18n.t("settings.input_max_tokens")).strip()

        if not new_value:
            return

        try:
            new_max_tokens = int(new_value)
            if new_max_tokens < 1:
                _console.print(f"[red]{i18n.t('settings.token_min')}[/red]")
                input(i18n.t("main.press_enter"))
                return
            elif new_max_tokens > 200000:
                _console.print(f"[red]{i18n.t('settings.token_max')}[/red]")
                input(i18n.t("main.press_enter"))
                return
            state.current_config['max_tokens'] = new_max_tokens
            config.save_config(state.current_config)
            log.info(f"最大 Token 数已更改: {new_max_tokens}")
            _console.print(f"[green]{i18n.t('settings.updated', value=new_max_tokens)}[/green]")
            input(i18n.t("main.press_enter"))
        except ValueError:
            _console.print(f"[red]{i18n.t('settings.invalid_number')}[/red]")
            input(i18n.t("main.press_enter"))

    def _run_prefix():
        """修改命令前缀。"""
        current_prefix = state.current_config.get('command_prefix', '/')
        _console.print()
        _console.print(Panel(Text(i18n.t("settings.prefix_panel", prefix=current_prefix)), title=i18n.t("settings.command_prefix"), border_style="cyan"))
        new_prefix = input(i18n.t("settings.input_prefix")).strip()

        if not new_prefix:
            return

        if len(new_prefix) > 10:
            new_prefix = new_prefix[:10]
            _console.print(f"[yellow]{i18n.t('settings.prefix_truncated', prefix=new_prefix)}[/yellow]")

        state.current_config['command_prefix'] = new_prefix
        config.save_config(state.current_config)
        cmd.save_commands()
        log.info(f"命令前缀已更改: {current_prefix} -> {new_prefix}")
        _console.print(f"[green]{i18n.t('settings.updated', value=new_prefix)}[/green]")
        input(i18n.t("main.press_enter"))

    def _render():
        from .key_nav import navigate

        def _label(item, i):
            if item["key"] == "max_tokens":
                return f"{i18n.t('settings.max_tokens')}: {state.current_config.get('max_tokens', 18000)}"
            return f"{i18n.t('settings.command_prefix')}: {state.current_config.get('command_prefix', '/')}"

        def _on_enter(item, i):
            item["action"]()
            return False  # 完成后回到导航，可继续配置其他项

        items = [
            {"key": "max_tokens", "action": _run_token},
            {"key": "command_prefix", "action": _run_prefix},
        ]
        navigate(i18n.t("settings.title"), i18n.t("settings.subtitle"), items, _label, _on_enter,
                 f"{i18n.t('settings.enter_configure')} | {i18n.t('settings.esc_back')}")
        _rebuild_client_and_chat()

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('set'),
                 command_info=f"╰─{cmd.get_command_description('set')}")


def _apply_model_config(model_info):
    """将模型专属配置写入 current_config 并保存。"""
    # 自定义模型有专属的 base_url 和 api_key
    if model_info.get("custom"):
        if model_info.get("base_url"):
            state.current_config["base_url"] = model_info["base_url"]
        if model_info.get("api_key"):
            state.current_config["api_key"] = model_info["api_key"]


def model_settings():
    """模型设置界面（上下键导航，k/a/d 为动作键）。"""
    cmd = state.cmd
    config = state.config
    log.info("进入模型设置")

    from modules.main_server.config import (
        get_available_models, add_custom_model, remove_custom_model,
        get_custom_model
    )

    def _render():
        from .key_nav import navigate

        current_model = state.current_config.get('model', constants.DEFAULT_MODEL)
        available_models = get_available_models()

        def _label(model_info, i):
            name_display = model_info['name']
            if model_info.get("custom"):
                name_display = f"* {name_display}"
            desc = model_info.get('description', '')
            marker = "✓" if model_info['name'] == current_model else ""
            line = f"{name_display}  {desc}".rstrip()
            if marker:
                line += f"  {marker}"
            return line

        def _on_enter(model_info, i):
            new_model = model_info["name"]
            state.current_config['model'] = new_model
            _apply_model_config(model_info)
            config.save_config(state.current_config)
            log.info(f"模型已切换: {new_model}")
            _rebuild_client_and_chat()
            _console.print(f"[green]{i18n.t('model.switched', name=new_model)}[/green]")
            input(i18n.t("main.press_enter"))
            return True  # 切换完成后退出模型设置

        def _extra_key(key, model_info, i):
            if key == 'k':
                # 修改 API 密钥
                _console.print()
                new_api_key = input(i18n.t("model.input_api_key")).strip()
                if new_api_key:
                    state.current_config['api_key'] = new_api_key
                    config.save_config(state.current_config)
                    log.info("API 密钥已更新")
                    _console.print(f"[green]{i18n.t('model.api_key_updated')}[/green]")
                    _rebuild_client_and_chat()
                    input(i18n.t("main.press_enter"))
                return True
            if key == 'a':
                # 添加自定义模型
                _add_custom_model_flow()
                return True
            if key == 'd':
                # 删除自定义模型
                if not model_info.get("custom"):
                    _console.print(f"[red]{i18n.t('model.not_custom')}[/red]")
                    input(i18n.t("main.press_enter"))
                    return True
                _delete_custom_model_flow(model_info)
                return True
            return False

        api_key = state.current_config.get('api_key', '')
        footer = (f"{i18n.t('model.api_key_label')}{'***' + api_key[-4:] if len(api_key) > 4 else ('已设置' if api_key else '未设置')}"
                  f" | {i18n.t('model.hint')}")
        navigate(i18n.t("model.title"), i18n.t("model.current", name=current_model),
                 available_models, _label, _on_enter, footer,
                 extra_key=_extra_key)

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('model'),
                 command_info=f"╰─{cmd.get_command_description('model')}")


def _add_custom_model_flow():
    """自定义模型添加流程。"""
    from modules.main_server.config import add_custom_model

    _console.print()
    _console.print(create_header_panel(i18n.t("model.add_title"), i18n.t("model.add_subtitle")))

    name = input(i18n.t("model.input_name")).strip()
    if not name:
        _console.print(f"[red]{i18n.t('model.name_required')}[/red]")
        input(i18n.t("main.press_enter"))
        return

    description = input(i18n.t("model.input_description")).strip()
    if not description:
        description = name

    base_url = input(i18n.t("model.input_base_url")).strip()
    if not base_url:
        _console.print(f"[red]{i18n.t('model.base_url_required')}[/red]")
        input(i18n.t("main.press_enter"))
        return

    api_key = input(i18n.t("model.api_key_label")).strip()
    if not api_key:
        _console.print(f"[red]{i18n.t('model.api_key_required')}[/red]")
        input(i18n.t("main.press_enter"))
        return

    context_str = input(i18n.t("model.input_context")).strip()
    context_window = 128000
    if context_str:
        try:
            context_window = int(context_str)
        except ValueError:
            _console.print(f"[yellow]{i18n.t('model.invalid_context')}[/yellow]")

    success, error = add_custom_model(name, description, base_url, api_key, context_window)
    if success:
        _console.print(f"[green]{i18n.t('model.added', name=name)}[/green]")
    else:
        _console.print(f"[red]{error}[/red]")
    input(i18n.t("main.press_enter"))


def _delete_custom_model_flow(model_info):
    """删除当前选中的自定义模型。"""
    from modules.main_server.config import remove_custom_model

    name = model_info["name"]
    _console.print()
    _console.print(create_header_panel(i18n.t("model.delete_title"), i18n.t("model.delete_subtitle")))
    confirm = input(i18n.t("model.confirm_delete", name=name)).strip().lower()
    if confirm not in ('y', 'yes'):
        return

    # 如果当前正在使用该模型，切回默认模型
    if state.current_config.get('model') == name:
        state.current_config['model'] = constants.DEFAULT_MODEL

    success, error = remove_custom_model(name)
    if success:
        _console.print(f"[green]{i18n.t('model.deleted', name=name)}[/green]")
    else:
        _console.print(f"[red]{error}[/red]")
    input(i18n.t("main.press_enter"))


def effort_settings():
    """思考深度设置界面（上下键导航）。"""
    cmd = state.cmd
    log.info("进入思考深度设置")

    _LEVELS = [
        ("fine", i18n.t("effort.fine")),
        ("normal", i18n.t("effort.normal")),
        ("high", i18n.t("effort.high")),
    ]

    def _render():
        from .key_nav import navigate

        def _label(level, i):
            name, desc = level
            marker = "✓" if state.effort_level == name else ""
            line = f"{name} - {desc}"
            if marker:
                line += f"  {marker}"
            return line

        def _on_enter(level, i):
            name, _ = level
            state.effort_level = name
            state.chat_instance.effort_level = name
            state.current_config['effort_level'] = name
            state.config.save_config(state.current_config)
            log.info(f"思考深度已更改: {name}")
            _console.print(f"[green]{i18n.t('main.effort_set', level=name)}[/green]")
            input(i18n.t("main.press_enter"))
            return True  # 应用后退出

        navigate(i18n.t("effort.title"), i18n.t("effort.subtitle", level=state.effort_level),
                 _LEVELS, _label, _on_enter,
                 i18n.t("effort.hint"))

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('effort'),
                 command_info=f"╰─{cmd.get_command_description('effort')}")


def toggle_tools():
    """切换工具启用/禁用状态。"""
    current_status = state.chat_instance.enable_tools
    new_status = not current_status
    state.chat_instance.enable_tool(new_status)
    status_text = i18n.t("tools.enabled") if new_status else i18n.t("tools.disabled")
    log.info(f"工具状态已切换: {status_text}")
    print(i18n.t("tools.toggled", status=status_text))
