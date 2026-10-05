"""聊天事件回调和 spinner 动画。"""
import sys
import time
import asyncio

from colorama import Fore, Style

from modules.bootstrap import constants
from modules.core import events, GenerationCancelled
from modules.logger import get_logger
from . import i18n
from .state import ui, state

log = get_logger("Dolphin.callback")

_SPINNER_FRAMES = constants.SPINNER_FRAMES


async def run_spinner(prefix: str):
    """运行工具调用等待的 spinner 动画。"""
    i = 0
    try:
        while True:
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            indent = "  " if (ui._indented_after_thinking and state.show_thinking) else ""
            sys.stdout.write(f"\r\033[K{indent}{Fore.CYAN}[{prefix}]{Style.RESET_ALL} {frame}")
            sys.stdout.flush()
            ui.at_line_start = False
            i += 1
            await asyncio.sleep(0.12)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # stdout 被重定向/关闭（如管道输出）时优雅退出，而不是留下未检索的异常
        log.debug(f"spinner 输出失败: {e}")


def _consume_task_result(task):
    """检索已结束任务的异常，避免 "Task exception was never retrieved"。"""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        log.debug(f"spinner 任务异常: {exc}")


def clear_tool_pending():
    """清除工具等待状态和 spinner。"""
    if ui._spinner_task and not ui._spinner_task.done():
        ui._spinner_task.cancel()
        ui._spinner_task.add_done_callback(_consume_task_result)
        ui._spinner_task = None
    ui._tool_pending = False


def _get_indent_prefix():
    """获取思考后内容的缩进前缀，返回统一的 2 空格缩进。

    折角符号已在思考结束时直接输出，因此后续内容只需缩进即可。
    仅当思考过程实际显示（show_thinking=True）时才返回缩进，
    否则返回空字符串，保持隐藏思考模式下的正常布局。
    """
    if not ui._indented_after_thinking:
        return ""
    if not state.show_thinking:
        return ""
    return "  "


def rollback_last_message():
    """回退最后一条用户消息及其后的 assistant/tool 消息（API 错误或用户中断）。"""
    if not state.chat_instance:
        return

    # 先丢弃流式缓冲残留，防止中断的半截回复在下一轮/退出时被恢复机制重新并入
    state.chat_instance.discard_stream_buffer()

    if not state.chat_instance.messages:
        return

    msgs = state.chat_instance.messages
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            del msgs[i:]
            if state.current_dir_id and state.current_conv_id:
                from modules.chater import conversation
                conversation.save_conversation(msgs, state.current_dir_id, state.current_conv_id)
            log.debug("API 错误后已回退用户消息及其后的 assistant/tool 消息")
            return

    log.debug("未找到用户消息，未执行回退")


def flush_context_usage():
    """在回显中打印暂存的 token 用量。"""
    cmd = state.cmd
    data = ui._pending_context_usage
    if data is None:
        return
    ui._pending_context_usage = None

    ratio = data.get('usage_ratio', 0)
    level = data.get('level')
    turn_completion = data.get('turn_completion_tokens', 0)
    pct = f"{ratio:.0%}"

    # 圆形进度条
    if ratio < 0.25:
        circle = "\u25cb"
    elif ratio < 0.5:
        circle = "\u25d4"
    elif ratio < 0.75:
        circle = "\u25d1"
    elif ratio < 0.95:
        circle = "\u25d5"
    else:
        circle = "\u25cf"

    # 告警提示
    if level == 'critical':
        print(f"\n{Fore.RED}上下文即将耗尽 ({pct})，建议 {cmd.get_command('clear')} 清空历史{Style.RESET_ALL}")
    elif level == 'high':
        print(f"\n{Fore.YELLOW}上下文使用率较高 ({pct})，建议 {cmd.get_command('clear')} 清空历史{Style.RESET_ALL}")
    elif level == 'warn':
        print(f"\n{Fore.LIGHTBLACK_EX}上下文使用率 {pct}{Style.RESET_ALL}")

    # 若流式回复末尾未换行，先换行再显示 token 统计，避免拼在同一行
    if not ui.at_line_start:
        sys.stdout.write("\n")
        ui.at_line_start = True
    print(f"{Fore.LIGHTBLACK_EX}[Token] 本轮 {turn_completion} | {circle} {pct}{Style.RESET_ALL}")


def chat_callback(event_type, data):
    """处理聊天事件的回调函数。"""
    cmd = state.cmd
    format_user_output_line = state.format_user_output_line

    if event_type == events.EVENT_THINKING:
        if ui.turn_first_output:
            ui.turn_first_output = False
        if state.show_thinking:
            print(f"{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_header')}{Style.RESET_ALL}\n{Fore.LIGHTBLACK_EX}{data['content']}{Style.RESET_ALL}")
            ui._indented_after_thinking = False
            ui.at_line_start = True
    elif event_type == events.EVENT_TOOL_START:
        clear_tool_pending()
        ui._tool_pending = True
        ui._spinner_task = asyncio.ensure_future(run_spinner(data['name']))
        log.info(f"工具开始执行: {data.get('name', 'unknown')}")
    elif event_type == events.EVENT_THINKING_START:
        ui._indented_after_thinking = False
        if ui.turn_first_output:
            ui.turn_first_output = False
        if state.show_thinking:
            print(f"{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_header')}{Style.RESET_ALL}")
            ui.at_line_start = True
        else:
            ui.thinking_start_time = time.time()
            log.debug("思考开始")
            print(f"\r\033[K{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_in_progress', elapsed=0)}{Style.RESET_ALL}", end="", flush=True)
            ui.at_line_start = False
    elif event_type == events.EVENT_THINKING_CHUNK:
        if state.show_thinking:
            print(f"{Fore.LIGHTBLACK_EX}{data['content']}{Style.RESET_ALL}", end="", flush=True)
        else:
            elapsed = int(time.time() - ui.thinking_start_time)
            print(f"\r\033[K{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_in_progress', elapsed=elapsed)}{Style.RESET_ALL}", end="", flush=True)
        ui.at_line_start = False
    elif event_type == events.EVENT_THINKING_END:
        if not state.show_thinking:
            elapsed = int(time.time() - ui.thinking_start_time)
            log.info(f"思考完成, 耗时={elapsed}s")
            print(f"\r\033[K{Fore.LIGHTBLACK_EX}╰─ {i18n.t('chat.thinking_done', elapsed=elapsed)}{Style.RESET_ALL}")
            ui.at_line_start = True
        ui._indented_after_thinking = not state.show_thinking
    elif event_type == events.EVENT_RESPONSE_CHUNK:
        if ui.turn_first_output:
            ui.turn_first_output = False
        content = data['content']
        if ui._indented_after_thinking:
            if '\n' in content:
                lines = content.split('\n')
                for line in lines[:-1]:
                    prefix = _get_indent_prefix()
                    if line:
                        print(f"{prefix}{line}")
                last = lines[-1]
                if last:
                    prefix = _get_indent_prefix()
                    print(f"{prefix}{last}", end="", flush=True)
            else:
                prefix = _get_indent_prefix()
                print(f"{prefix}{content}", end="", flush=True)
        else:
            print(content, end="", flush=True)
        ui.at_line_start = content.endswith('\n')
    elif event_type == events.EVENT_RESPONSE_END:
        ui._indented_after_thinking = False
    elif event_type == events.EVENT_TOOL_CALLS:
        clear_tool_pending()
        sys.stdout.write("\n")
        sys.stdout.flush()
        ui.at_line_start = True
        log.info(f"工具调用列表: {[call.get('name', 'unknown') for call in data.get('calls', [])]}")
        prefix = _get_indent_prefix()
        print(f"{prefix}{Fore.BLUE}--工具调用:{Style.RESET_ALL}")
        for call in data['calls']:
            indent = "  " if (ui._indented_after_thinking and state.show_thinking) else ""
            print(f"{indent}{Fore.BLUE}  - {call['name']}{Style.RESET_ALL}")
            if call.get('arguments'):
                print(f"{indent}{Fore.BLUE}    参数: {call['arguments']}{Style.RESET_ALL}")
    elif event_type == events.EVENT_TOOL_RESULT:
        indent = "  " if (ui._indented_after_thinking and state.show_thinking) else ""
        if data['formatted']:
            print(f"{indent}{Fore.GREEN}--结果:\n{indent}{data['formatted']}{Style.RESET_ALL}")
        else:
            print(f"{indent}{Fore.GREEN}--结果: {data['raw']}{Style.RESET_ALL}")
        ui.at_line_start = True
    elif event_type == events.EVENT_USER_OUTPUT:
        clear_tool_pending()
        line = format_user_output_line(data)
        sys.stdout.write(f"\r\033[K{line}\n")
        sys.stdout.flush()
        ui.at_line_start = True
    elif event_type == events.EVENT_USER_INPUT_REQUIRED:
        clear_tool_pending()
        sys.stdout.write("\n")
        sys.stdout.flush()
        log.info("需要用户输入")
        print(f"{Fore.YELLOW}[需要输入]{Style.RESET_ALL}")
        print(f"  {data.get('prompt', '请输入信息')}")
        if data.get('default_value'):
            print(f"  默认值: {data.get('default_value')}")
        try:
            user_input = input("\n请输入: ").strip()
        except KeyboardInterrupt:
            # 交互等待中中断：转为生成中断，避免退出进程留下未闭环结构
            raise GenerationCancelled from None
        if not user_input and data.get('default_value'):
            user_input = data.get('default_value')
        return user_input
    elif event_type == events.EVENT_CONFIRMATION_REQUIRED:
        clear_tool_pending()
        sys.stdout.write("\n")
        sys.stdout.flush()
        log.info(f"需要用户确认: {data.get('action', 'unknown')}")
        print(f"{Fore.YELLOW}[需要确认]{Style.RESET_ALL}")
        print(f"  操作: {data.get('action', 'unknown')}")
        if data.get('script_preview'):
            print(f"  脚本预览:")
            print(f"  {data.get('script_preview')}")
        if data.get('file_path'):
            print(f"  文件: {data.get('file_path')}")
        if data.get('work_directory'):
            print(f"  工作目录: {data.get('work_directory')}")
        if data.get('error'):
            print(f"  原因: {data.get('error')}")
        try:
            return input("\n是否确认此操作? (y/n): ").lower()
        except KeyboardInterrupt:
            raise GenerationCancelled from None
    elif event_type == events.EVENT_OPERATION_CANCELED:
        log.info("操作已取消")
        print("操作已取消")
    elif event_type == events.EVENT_OPERATION_CONFIRMED:
        log.info("操作已确认，正在执行")
        print("操作已确认，正在执行...")
    elif event_type == events.EVENT_CONSOLE_OUTPUT:
        content = data.get('content', '')
        level = data.get('level', 'info')
        if level == 'error':
            print(f"\n{Fore.RED}错误: {content}{Style.RESET_ALL}")
        elif level == 'warning':
            print(f"\n{Fore.YELLOW}警告: {content}{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.GREEN}信息: {content}{Style.RESET_ALL}")
    elif event_type == events.EVENT_MAX_ITERATIONS_REACHED:
        current_iterations = data.get('iterations', 0)
        hard_limit = data.get('hard_limit', 100)
        remaining = hard_limit - current_iterations
        log.warning(f"工具调用达到迭代上限: {current_iterations}/{hard_limit}")
        print(f"\n{Fore.YELLOW}工具调用已达 {current_iterations} 次 (上限 {hard_limit} 次，剩余 {remaining} 次){Style.RESET_ALL}")
        try:
            return input("是否继续对话? (y/n): ").lower()
        except KeyboardInterrupt:
            raise GenerationCancelled from None
    elif event_type == events.EVENT_CONTEXT_USAGE:
        ui._pending_context_usage = data
    elif event_type == events.EVENT_CONTEXT_COMPACT_START:
        # 与工具调用共用同一等待动画槽，整理期间显示 spinner
        clear_tool_pending()
        ui._tool_pending = True
        ui._spinner_task = asyncio.ensure_future(run_spinner("compact"))
    elif event_type == events.EVENT_CONTEXT_COMPACTED:
        # 收尾：停止等待动画并给出结果
        clear_tool_pending()
        error = data.get('error')
        skipped = data.get('skipped')
        if error or skipped:
            # 未执行/无需压缩：就地打印一行提示
            if not ui.at_line_start:
                sys.stdout.write("\n")
                ui.at_line_start = True
            if error:
                print(f"{Fore.YELLOW}上下文整理未执行: {error}{Style.RESET_ALL}")
            else:
                print(f"{Fore.GREEN}无需压缩（{skipped}）{Style.RESET_ALL}")
        else:
            # 成功：整理记录已写入对话 display（灰色 [Compact] 已完成压缩），
            # 直接刷新界面呈现整理后的历史
            from .header import print_header, print_conversation_history
            state.screen_refresh.refresh(print_header, print_conversation_history)
            ui.at_line_start = True
