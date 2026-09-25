import json
import os
import time
from modules.chater import conversation
from modules.chater import dpc_manager
from modules.bootstrap import constants
from modules.logger import get_logger
from colorama import Fore, Style

log = get_logger("Dolphin.conversation_loader")

# style 名称 → colorama 前缀的映射，skill 通过 parts 中的 style 字段引用
_STYLE_MAP = {
    "default": "",
    "green": Fore.GREEN,
    "red": Fore.RED,
    "yellow": Fore.YELLOW,
    "gray": Fore.LIGHTBLACK_EX,
    "cyan": Fore.CYAN,
    "blue": Fore.BLUE,
}


def _render_parts(parts: list) -> str:
    """将结构化 parts 列表渲染为带颜色的终端字符串。"""
    rendered = []
    for part in parts:
        if isinstance(part, str):
            rendered.append(part)
            continue
        text = part.get("text", "")
        style_name = part.get("style", "default")
        prefix = _STYLE_MAP.get(style_name, "")
        if prefix:
            rendered.append(f"{prefix}{text}{Style.RESET_ALL}")
        else:
            rendered.append(text)
    return " ".join(rendered)


def format_user_output_line(uo: dict) -> str:
    """将 user_output 字典渲染为终端显示行，统一实时回调和历史回显的格式。

    支持两种格式：
    - 结构化: {"label": "...", "parts": [{"text": "...", "style": "green"}, ...]}
    - 向后兼容: {"label": "...", "content": "已含颜色代码的字符串"}
    """
    label = uo.get('label', '')
    parts = uo.get('parts')
    if parts:
        content = _render_parts(parts)
    else:
        content = uo.get('content', '')
    if label:
        return f"{Fore.CYAN}[{label}]{Style.RESET_ALL} {content}"
    return content


def load_and_activate(chat_instance, dir_id, conv_id, conv_name, work_dir):
    start = time.perf_counter()
    loaded = chat_instance.load_conversation(dir_id, conv_id)
    if not loaded:
        chat_instance.clear_history()
        conversation.init_conversation(dir_id, conv_id, conv_name, work_dir)
        log.info(f"初始化空对话文件: {conv_name} ({conv_id})")
    else:
        log.info(f"加载对话成功: {conv_name} ({conv_id})")

    dpc_manager.set_current_by_id(work_dir, conv_id)

    elapsed = time.perf_counter() - start
    log.info(f"加载并激活对话完成: {conv_name} ({conv_id}), 耗时={elapsed:.3f}s")

    return {
        'conv_name': conv_name,
        'dir_id': dir_id,
        'conv_id': conv_id,
    }


def format_conversation_history(messages, show_thinking):
    """格式化会话历史为文本，供回显展示。"""
    from modules.CLIserver import i18n

    start = time.perf_counter()
    if not messages:
        return ""

    tool_ids_have_uo = set()
    for msg in messages:
        if msg.get('role') == 'tool' and msg.get('user_output'):
            tool_ids_have_uo.add(msg.get('tool_call_id'))

    lines = []
    for msg in messages:
        if msg.get(constants.MSG_DISPLAY_FIELD) is False:
            continue
        role = msg.get('role', '')
        content = msg.get('content', '')
        if role == 'system':
            continue
        elif role == 'user':
            # 合成图片附件轮（read_image 注入）：渲染为灰色标签而非用户发言
            user_uo = msg.get('user_output')
            if user_uo:
                lines.append(format_user_output_line(user_uo))
                continue
            lines.append("")
            lines.append(f"{Fore.WHITE}>{Style.RESET_ALL} {content}")
            # @ 附图的图片标签
            for img in msg.get(constants.MSG_IMAGES_FIELD) or []:
                name = os.path.basename(img.get('path', ''))
                lines.append(format_user_output_line(
                    {"label": "Image", "parts": [{"text": name, "style": "gray"}]}
                ))
        elif role == 'assistant':
            has_reasoning = bool(msg.get('reasoning_content'))
            if has_reasoning:
                if show_thinking:
                    lines.append(f"{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_header')}{Style.RESET_ALL}")
                    lines.append(f"{Fore.LIGHTBLACK_EX}{msg['reasoning_content']}{Style.RESET_ALL}")
                else:
                    lines.append(f"{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_done_no_time')}{Style.RESET_ALL}")
            if content:
                lines.append(content)
            if msg.get('tool_calls'):
                all_have_uo = all(tc['id'] in tool_ids_have_uo for tc in msg['tool_calls'] if tc.get('id'))
                if all_have_uo:
                    continue
                indent = ""
                lines.append(f"{indent}{Fore.BLUE}--工具调用:{Style.RESET_ALL}")
                for tc in msg['tool_calls']:
                    fn = tc['function']
                    lines.append(f"{indent}{Fore.BLUE}  - {fn['name']}{Style.RESET_ALL}")
                    args = fn.get('arguments', '')
                    if args:
                        try:
                            args_parsed = json.loads(args)
                            lines.append(f"{indent}{Fore.BLUE}    参数: {json.dumps(args_parsed, ensure_ascii=False, indent=4)}{Style.RESET_ALL}")
                        except (json.JSONDecodeError, TypeError):
                            lines.append(f"{indent}{Fore.BLUE}    参数: {args}{Style.RESET_ALL}")
        elif role == 'tool':
            user_output = msg.get('user_output')
            if user_output:
                lines.append(format_user_output_line(user_output))
            else:
                tool_content = msg.get('content', '')
                if tool_content:
                    lines.append(f"{Fore.GREEN}--结果:{Style.RESET_ALL}")
                    lines.append(f"{Fore.GREEN}{tool_content}{Style.RESET_ALL}")

    result = "\n".join(lines)
    elapsed = time.perf_counter() - start
    log.debug(f"渲染对话历史完成: {len(messages)} 条消息, 耗时={elapsed:.3f}s")
    return result
