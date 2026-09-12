"""设置模式、模型设置和工具切换界面（业务操作委托 core.services）。"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from modules.logger import get_logger
from modules.bootstrap import constants
from modules.core.services import chat_service, config_service
from . import i18n
from .state import state

log = get_logger("Dolphin.settings")
_console = Console()


def settings_mode():
    """进入设置界面（上下键选择配置项）。"""
    cmd = state.cmd
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
        except ValueError:
            _console.print(f"[red]{i18n.t('settings.invalid_number')}[/red]")
            input(i18n.t("main.press_enter"))
            return

        result = config_service.set_max_tokens(state, new_max_tokens)
        if result.get('success'):
            _console.print(f"[green]{i18n.t('settings.updated', value=new_max_tokens)}[/green]")
        elif result.get('error') == 'min':
            _console.print(f"[red]{i18n.t('settings.token_min')}[/red]")
        else:
            _console.print(f"[red]{i18n.t('settings.token_max')}[/red]")
        input(i18n.t("main.press_enter"))

    def _run_prefix():
        """修改命令前缀。"""
        current_prefix = state.current_config.get('command_prefix', '/')
        _console.print()
        _console.print(Panel(Text(i18n.t("settings.prefix_panel", prefix=current_prefix)), title=i18n.t("settings.command_prefix"), border_style="cyan"))
        new_prefix = input(i18n.t("settings.input_prefix")).strip()

        if not new_prefix:
            return

        result = config_service.set_command_prefix(state, new_prefix)
        if result.get('truncated'):
            _console.print(f"[yellow]{i18n.t('settings.prefix_truncated', prefix=result['value'])}[/yellow]")
        _console.print(f"[green]{i18n.t('settings.updated', value=result['value'])}[/green]")
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
        # 重建实例使 max_tokens 等配置生效
        chat_service.rebuild_chat_instance(state)
        print("客户端已更新")

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('set'),
                 command_info=f"╰─{cmd.get_command_description('set')}")


def model_settings():
    """模型设置界面（一级列表，k/a/d 为动作键）。"""
    cmd = state.cmd
    log.info("进入模型设置")

    from modules.main_server.config import get_available_models

    def _render():
        from .key_nav import navigate

        def _current_model():
            return state.current_config.get('model', constants.DEFAULT_MODEL)

        def _footer():
            api_key = state.current_config.get('api_key', '')
            shown = f"***{api_key[-4:]}" if len(api_key) > 4 else ('已设置' if api_key else '未设置')
            return f"{i18n.t('model.api_key_label')}{shown} | {i18n.t('model.hint')}"

        def _list_state():
            """刷新列表、副标题与底部提示：增删模型后需要重新取值。"""
            return {
                "options": get_available_models(),
                "subtitle": i18n.t("model.current", name=_current_model()),
                "hint": _footer(),
            }

        def _label(model_info, i):
            name_display = model_info['name']
            if model_info.get("custom"):
                name_display = f"* {name_display}"
            desc = model_info.get('description', '')
            marker = "✓" if model_info['name'] == _current_model() else ""
            line = f"{name_display}  {desc}".rstrip()
            if marker:
                line += f"  {marker}"
            return line

        def _on_enter(model_info, i):
            result = config_service.switch_model(state, model_info)
            _console.print(f"[green]{i18n.t('model.switched', name=result['value'])}[/green]")
            print("客户端已更新")
            input(i18n.t("main.press_enter"))
            return True  # 切换完成后退出模型设置

        def _extra_key(key, model_info, i):
            if key == 'e':
                _edit_model_flow(model_info)
                return True
            if key == 'a':
                _add_custom_model_flow()
                return True
            if key == 'd':
                _delete_custom_model_flow(model_info)
                return True
            return False

        navigate(i18n.t("model.title"), i18n.t("model.current", name=_current_model()),
                 get_available_models(), _label, _on_enter, _footer(),
                 extra_key=_extra_key, refresh_fn=_list_state)

    from .screen_refresh import enter_screen
    enter_screen(_render,
                 command_input=cmd.get_command('model'),
                 command_info=f"╰─{cmd.get_command_description('model')}")


def _required_validator(message):
    """构造"不能为空"字段校验器。"""
    def _validate(text):
        value = text.strip()
        if not value:
            return False, message, text
        return True, "", value
    return _validate


def _context_window_validator(text):
    """上下文窗口校验：留空表示用默认值，非正整数报错。"""
    value = text.strip()
    if not value:
        return True, "", ""
    try:
        number = int(value)
    except ValueError:
        return False, i18n.t("model.invalid_context"), text
    if number <= 0:
        return False, i18n.t("model.invalid_context"), text
    return True, "", str(number)


def _custom_model_fields():
    """构造添加模型表单的字段定义（二级表单页用）。"""
    return [
        {"key": "name", "label": i18n.t("model.field_name"),
         "prompt": i18n.t("model.input_name"), "value": "",
         "required": True, "required_message": i18n.t("model.name_required"),
         "validate": _required_validator(i18n.t("model.name_required"))},
        {"key": "description", "label": i18n.t("model.field_description"),
         "prompt": i18n.t("model.input_description"), "value": ""},
        {"key": "base_url", "label": i18n.t("model.field_base_url"),
         "prompt": i18n.t("model.input_base_url"), "value": "",
         "required": True, "required_message": i18n.t("model.base_url_required"),
         "validate": _required_validator(i18n.t("model.base_url_required"))},
        {"key": "api_key", "label": i18n.t("model.field_api_key"),
         "prompt": i18n.t("model.api_key_label"), "value": "",
         "required": True, "mask": True,
         "required_message": i18n.t("model.api_key_required"),
         "validate": _required_validator(i18n.t("model.api_key_required"))},
        {"key": "context_window", "label": i18n.t("model.field_context"),
         "prompt": i18n.t("model.input_context"), "value": "",
         "validate": _context_window_validator},
    ]


def _add_custom_model_flow():
    """添加自定义模型：二级字段表单 + 三级字段编辑页。"""
    from modules.main_server.config import add_custom_model, DEFAULT_CONTEXT_WINDOW
    from .form import form_nav

    values = form_nav(i18n.t("model.add_title"), i18n.t("model.add_subtitle"),
                      _custom_model_fields(), submit_label=i18n.t("model.submit"))
    if values is None:
        return

    name = values["name"]
    context_window = int(values["context_window"]) if values["context_window"] else DEFAULT_CONTEXT_WINDOW
    success, error = add_custom_model(name, values["description"] or name,
                                      values["base_url"], values["api_key"], context_window)
    if success:
        _console.print(f"[green]{i18n.t('model.added', name=name)}[/green]")
    else:
        _console.print(f"[red]{error}[/red]")
    input(i18n.t("main.press_enter"))


def _edit_model_flow(model_info):
    """修改已有模型：默认模型合并成组仅改密钥，自定义模型可改除名称外的字段。"""
    if model_info.get("custom"):
        _edit_custom_model_flow(model_info)
    else:
        _edit_builtin_group_flow(model_info)


def _builtin_group_names(model_info):
    """返回与给定内置模型共用同一密钥变量的模型名列表。"""
    from modules.main_server.config import get_available_models

    env_name = (model_info or {}).get("api_key_env")
    names = [m["name"] for m in get_available_models()
             if not m.get("custom") and m.get("api_key_env") == env_name]
    return names or [model_info.get("name", "")]


def _edit_builtin_group_flow(model_info):
    """默认模型组：合并展示共用密钥的模型，页内仅允许修改密钥。"""
    from modules.main_server.config import resolve_model_credentials
    from .form import form_nav

    group = _builtin_group_names(model_info)
    current_key = resolve_model_credentials(group[0]).get("api_key", "")
    fields = [{
        "key": "api_key",
        "label": i18n.t("model.field_api_key"),
        "prompt": i18n.t("model.builtin_key_prompt"),
        "value": current_key,
        "mask": True,
        # 尚未设置密钥时必填，否则留空表示保持原值
        "required": not current_key,
        "required_message": i18n.t("model.api_key_required"),
        "validate": None if current_key else _required_validator(i18n.t("model.api_key_required")),
    }]
    values = form_nav(i18n.t("model.builtin_group_title"),
                      i18n.t("model.builtin_group_subtitle", models=" / ".join(group)),
                      fields, submit_label=i18n.t("model.submit_save"))
    if values is None or not values.get("api_key", "").strip():
        return

    result = config_service.update_model(state, group[0], {"api_key": values["api_key"].strip()})
    _report_model_update(result, group[0])


def _edit_custom_model_flow(model_info):
    """自定义模型：可修改除模型名以外的所有字段。"""
    from modules.main_server.config import resolve_model_credentials
    from .form import form_nav

    name = model_info["name"]
    current_key = resolve_model_credentials(name).get("api_key", "")
    fields = [
        {"key": "description", "label": i18n.t("model.field_description"),
         "prompt": i18n.t("model.input_description"),
         "value": model_info.get("description", "")},
        {"key": "base_url", "label": i18n.t("model.field_base_url"),
         "prompt": i18n.t("model.input_base_url"),
         "value": model_info.get("base_url", ""),
         "required": True, "required_message": i18n.t("model.base_url_required"),
         "validate": _required_validator(i18n.t("model.base_url_required"))},
        {"key": "context_window", "label": i18n.t("model.field_context"),
         "prompt": i18n.t("model.input_context"),
         "value": str(model_info.get("context_window", "")),
         "validate": _context_window_validator},
        {"key": "api_key", "label": i18n.t("model.field_api_key"),
         "prompt": i18n.t("model.api_key_prompt", name=name),
         "value": current_key,
         "mask": True,
         # 尚未设置密钥时必填，否则留空表示保持原值
         "required": not current_key,
         "required_message": i18n.t("model.api_key_required"),
         "validate": None if current_key else _required_validator(i18n.t("model.api_key_required"))},
    ]
    values = form_nav(i18n.t("model.edit_title", name=name),
                      i18n.t("model.edit_subtitle"), fields,
                      submit_label=i18n.t("model.submit_save"))
    if values is None:
        return

    _report_model_update(config_service.update_model(state, name, {
        "description": values.get("description") or name,
        "base_url": values["base_url"],
        "context_window": int(values["context_window"]) if values.get("context_window") else None,
        "api_key": values.get("api_key", "").strip(),
    }), name)


def _report_model_update(result, name):
    """统一输出模型更新结果。"""
    if result.get("success"):
        _console.print(f"[green]{i18n.t('model.updated', name=name)}[/green]")
        if result.get("rebuilt"):
            print("客户端已更新")
    else:
        _console.print(f"[red]{result.get('error')}[/red]")
    input(i18n.t("main.press_enter"))


def _delete_custom_model_flow(model_info):
    """删除自定义模型：二级确认页。"""
    from .form import confirm_nav

    if not model_info.get("custom"):
        _console.print(f"[red]{i18n.t('model.not_custom')}[/red]")
        input(i18n.t("main.press_enter"))
        return

    name = model_info["name"]
    confirmed = confirm_nav(i18n.t("model.delete_title"),
                            i18n.t("model.delete_subtitle"),
                            i18n.t("model.confirm_delete", name=name),
                            i18n.t("form.cancel"))
    if not confirmed:
        return

    result = config_service.remove_custom_model(state, name)
    if result.get('success'):
        _console.print(f"[green]{i18n.t('model.deleted', name=name)}[/green]")
    else:
        _console.print(f"[red]{result.get('error')}[/red]")
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
            result = config_service.set_effort_level(state, name)
            _console.print(f"[green]{i18n.t('main.effort_set', level=result['value'])}[/green]")
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
