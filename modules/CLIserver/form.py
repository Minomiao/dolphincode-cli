"""表单与单字段输入的三级交互组件。

配合 key_nav 构成三级界面：
    一级：列表（key_nav.navigate，如模型列表）
    二级：字段表单（form_nav，字段清单，回车进入编辑）
    三级：单字段编辑页（text_input）：顶部信息表集中展示提示，下方以 "> " 普通输入

字段编辑页用普通行输入（支持输入法、粘贴、退格），不使用原始按键读取；
表单与确认页在无交互控制台（管道/重定向）时回退为逐行 input。

字段定义（dict）约定：
    key              字段标识（提交结果的键）
    label            字段名（表单行与编辑页标题）
    prompt           编辑页副标题 / 回退模式下的输入提示
    value            当前值
    required         是否必填
    required_message 必填校验失败时的提示（回退模式使用）
    mask             是否掩码显示（密钥）
    validate         callable(文本) -> (ok, 错误信息, 规范值)
"""
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from modules.logger import get_logger
from . import console_input
from . import i18n
from .key_nav import navigate
from .screen_refresh import clear_screen

log = get_logger("Dolphin.form")
_console = Console()

_INPUT_PROMPT = "> "


def _run_validate(validate, text):
    """执行字段校验，返回 (ok, 错误信息, 规范值)。"""
    if validate is None:
        return True, "", text
    try:
        return validate(text)
    except Exception as e:
        log.warning(f"字段校验异常: {e}")
        return False, str(e), text


def _masked(text):
    """把密钥等敏感内容替换为等长掩码。"""
    return "•" * len(text)


def _header_text(text):
    """去掉提示文案末尾的冒号，便于在信息表中展示。"""
    return text.rstrip().rstrip(":").rstrip()


def _editor_table(title, subtitle, value, mask, required, error, hint):
    """构造编辑页顶部的信息表：字段、提示、当前值、错误与操作说明。"""
    table = Table(box=box.ROUNDED, border_style="cyan",
                  show_header=False, padding=(0, 1))
    table.add_column(style="dim", no_wrap=True)
    table.add_column()

    table.add_row(i18n.t("form.row_field"), Text(title, style="bold cyan"))

    prompt = _header_text(subtitle) if subtitle else ""
    if required:
        prompt = f"{prompt} [{i18n.t('form.required')}]".strip()
    if prompt:
        table.add_row(i18n.t("form.row_prompt"), prompt)

    shown = _masked(value) if mask else value
    table.add_row(i18n.t("form.row_current"), shown or i18n.t("form.empty"))

    if error:
        table.add_row(i18n.t("form.row_error"), Text(error, style="red"))
    table.add_row(i18n.t("form.row_action"), hint)
    return table


def text_input(title, subtitle="", value="", mask=False, required=False,
               validate=None, hint=None, fallback=None):
    """三级页面：单字段编辑页。

    顶部信息表集中展示字段、提示、当前值与校验错误，下方以 "> " 引导普通行输入。
    留空表示保持原值；校验失败时停留在本页重新提示。

    Args:
        title: 页面标题（字段名）
        subtitle: 输入提示
        value: 编辑框的初始文本
        mask: 是否掩码显示
        required: 是否必填（仅用于展示必填标记）
        validate: callable(文本) -> (ok, 错误信息, 规范值)
        hint: 操作说明，缺省用通用编辑提示
        fallback: 留空时保留的值（缺省与 value 相同）

    Returns:
        (True, 新值) 已确认 / (False, 原值) 已取消
    """
    keep = value if fallback is None else fallback
    original = keep
    hint = hint or i18n.t("form.edit_hint")
    error = ""

    while True:
        clear_screen()
        _console.print()
        _console.print(_editor_table(title, subtitle, keep, mask, required, error, hint))
        _console.print()
        try:
            raw = input(_INPUT_PROMPT).strip()
        except (KeyboardInterrupt, EOFError):
            # 与列表界面的 Esc 等价：取消本次编辑并保留原值
            print()
            return False, original

        ok, message, normalized = _run_validate(validate, raw or keep)
        if ok:
            return True, normalized
        error = message


def form_nav(title, subtitle, fields, submit_label, hint=None):
    """二级页面：字段表单。

    ↑/↓ 选择字段，回车进入该字段的编辑页；选中提交项并回车则提交。
    提交时若必填字段仍为空，会自动打开第一个未填字段的编辑页。

    Args:
        title: 页面标题
        subtitle: 页面副标题
        fields: 字段定义列表（见模块 docstring）
        submit_label: 提交项文案
        hint: 底部提示，缺省用通用表单提示

    Returns:
        {字段key: 值} 已提交 / None 已取消
    """
    if not console_input.is_available():
        return _form_nav_fallback(fields)

    hint = hint or i18n.t("form.hint")
    submit_item = {"key": "__submit__", "label": submit_label}
    options = list(fields) + [submit_item]
    result = {"values": None}

    def _display(field):
        current = field.get("value", "")
        if not current:
            return i18n.t("form.empty")
        return _masked(current) if field.get("mask") else current

    def _label(field, index):
        if field.get("key") == "__submit__":
            return field["label"]
        required_mark = f" [{i18n.t('form.required')}]" if field.get("required") else ""
        return f"{field['label']}: {_display(field)}{required_mark}"

    def _edit(field):
        current = field.get("value", "")
        # 编辑框从空开始（避免在旧值上追加），留空即保持原值
        ok, new_value = text_input(field.get("label", ""), field.get("prompt", ""),
                                   value="", fallback=current,
                                   mask=field.get("mask", False),
                                   required=field.get("required", False),
                                   validate=field.get("validate"))
        if ok:
            field["value"] = new_value

    def _on_enter(field, index):
        if field.get("key") != "__submit__":
            _edit(field)
            return False
        missing = [f for f in fields if f.get("required") and not f.get("value")]
        if missing:
            log.info(f"表单必填项未完成，跳转到字段: {missing[0].get('key')}")
            _edit(missing[0])
            return False
        result["values"] = {f["key"]: f.get("value", "") for f in fields}
        return True

    navigate(title, subtitle, options, _label, _on_enter, hint)
    return result["values"]


def _form_nav_fallback(fields):
    """非交互回退：按顺序逐行输入各字段。"""
    for field in fields:
        prompt = field.get("prompt") or field.get("label", "")
        while True:
            raw = input(f"{prompt}[{field.get('value', '')}] " if field.get("value")
                        else prompt).strip()
            if not raw:
                if field.get("required") and not field.get("value"):
                    _console.print(f"[red]{field.get('required_message', '')}[/red]")
                    continue
                break
            ok, message, normalized = _run_validate(field.get("validate"), raw)
            if ok:
                field["value"] = normalized
                break
            _console.print(f"[red]{message}[/red]")
    return {f["key"]: f.get("value", "") for f in fields}


def confirm_nav(title, message, confirm_label, cancel_label, hint=None):
    """二级页面：确认页（确认 / 取消 两项列表）。

    Returns:
        True 已确认 / False 已取消
    """
    options = [
        {"key": "confirm", "label": confirm_label},
        {"key": "cancel", "label": cancel_label},
    ]
    result = {"confirmed": False}

    def _label(option, index):
        return option["label"]

    def _on_enter(option, index):
        result["confirmed"] = option["key"] == "confirm"
        return True

    navigate(title, message, options, _label, _on_enter,
             hint or i18n.t("form.hint"))
    return result["confirmed"]
