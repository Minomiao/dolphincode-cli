"""主命令循环：解析用户输入并分发到各子模块。"""
import sys

from colorama import Fore, Style

from modules.logger import get_logger
from . import i18n
from .state import ui, state
from .callback import chat_callback, clear_tool_pending, rollback_last_message
from .changes import handle_post_chat_changes
from .header import print_header, print_conversation_history
from .settings import settings_mode, model_settings, toggle_tools, effort_settings
from .conversation_ops import (
    open_work_directory, new_conversation, load_conversation, select_conversation
)
from .display import show_help, show_tools, show_skills

log = get_logger("Dolphin.main_loop")


def _pre_send_check():
    """发送消息前的必要检查。"""
    cmd = state.cmd
    missing = []
    if not state.current_config.get("api_key"):
        missing.append("API密钥")
    if not state.current_config.get("model"):
        missing.append("模型")
    return missing


async def main():
    """主命令循环。"""
    cmd = state.cmd
    config = state.config
    chat = state.chat
    screen_refresh = state.screen_refresh

    while True:
        try:
            ui.turn_first_output = True
            user_input = input("\n> ").strip()

            if not user_input:
                continue

            current_prefix = state.current_config.get('command_prefix', '/')
            if user_input.startswith(current_prefix):
                raw = user_input[len(current_prefix):].strip()
                parts = raw.split(maxsplit=1)
                keyword = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if keyword == cmd.get_command_keyword('help'):
                    show_help()
                    continue
                elif keyword == cmd.get_command_keyword('clear'):
                    state.chat_instance.clear_history()
                    screen_refresh.refresh(print_header, print_conversation_history, i18n.t("main.history_cleared"), show_history=False)
                    continue
                elif keyword == cmd.get_command_keyword('model'):
                    model_settings()
                    continue
                elif keyword == cmd.get_command_keyword('set'):
                    settings_mode()
                    continue
                elif keyword == cmd.get_command_keyword('open'):
                    open_work_directory(args or None)
                    continue
                elif keyword == cmd.get_command_keyword('new'):
                    new_conversation(args)
                    continue
                elif keyword == cmd.get_command_keyword('list'):
                    select_conversation()
                    continue
                elif keyword == cmd.get_command_keyword('load'):
                    load_conversation(args)
                    continue
                elif keyword == cmd.get_command_keyword('back'):
                    continue
                elif keyword == cmd.get_command_keyword('quit'):
                    log.info("用户退出程序")
                    print(i18n.t("main.goodbye"))
                    break
                elif keyword == cmd.get_command_keyword('tools'):
                    show_tools()
                    continue
                elif keyword == cmd.get_command_keyword('skills'):
                    show_skills()
                    continue
                elif keyword == cmd.get_command_keyword('changes'):
                    from .changes import handle_pending_changes
                    handle_pending_changes()
                    continue
                elif keyword == cmd.get_command_keyword('showthinking'):
                    if args:
                        arg = args.lower()
                        if arg not in ('on', 'off'):
                            print(i18n.t("main.invalid_arg", arg=arg))
                            continue
                        target = (arg == 'on')
                        if state.show_thinking == target:
                            status = i18n.t("main.on") if state.show_thinking else i18n.t("main.off")
                            print(i18n.t("main.thinking_already", status=status))
                            continue
                        state.show_thinking = target
                        state.current_config['show_thinking'] = target
                        state.config.save_config(state.current_config)
                        status = i18n.t("main.on") if state.show_thinking else i18n.t("main.off")
                        screen_refresh.refresh(print_header, print_conversation_history, i18n.t("main.thinking_set", status=status))
                    else:
                        status = i18n.t("main.on") if state.show_thinking else i18n.t("main.off")
                        print(i18n.t("main.thinking_current", status=status))
                    continue
                elif keyword == cmd.get_command_keyword('effort'):
                    if args:
                        level = args.lower()
                        if level in ['normal', 'fine', 'high']:
                            state.effort_level = level
                            state.chat_instance.effort_level = level
                            state.current_config['effort_level'] = level
                            state.config.save_config(state.current_config)
                            print(i18n.t("main.effort_set", level=level))
                        else:
                            print(i18n.t("main.effort_invalid"))
                    else:
                        # 无参数时进入上下键选择界面
                        effort_settings()
                    continue
                elif keyword == cmd.get_command_keyword('toggle'):
                    toggle_tools()
                    continue
                elif keyword == cmd.get_command_keyword('language'):
                    from .language import language_settings
                    language_settings()
                    continue
                else:
                    print(i18n.t("main.unknown_command", keyword=keyword))
                    continue

            # 发送消息前检查
            missing = _pre_send_check()
            if missing:
                missing_text = i18n.t("main.list_separator").join(missing)
                print(f"{Fore.RED}{i18n.t('main.missing_config', missing=missing_text, command=cmd.get_command('model'))}{Style.RESET_ALL}")
                log.warning(f"发送消息前检查失败: 缺少{missing_text}")
                continue

            try:
                await state.chat_instance.chat_stream(user_input)
                handle_post_chat_changes()
            except (state.AuthenticationError, state.RateLimitError,
                    state.APIConnectionError, state.APIError) as e:
                print(f"\n{Fore.RED}{i18n.t('main.api_error', error=e)}{Style.RESET_ALL}")
                log.error(f"API 错误: {e}", exc_info=True)
                rollback_last_message()
                clear_tool_pending()
            except Exception as e:
                print(f"\n{Fore.RED}{i18n.t('main.error', error=e)}{Style.RESET_ALL}")
                log.error(f"聊天错误: {e}", exc_info=True)
                clear_tool_pending()

        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}{i18n.t('main.interrupted')}{Style.RESET_ALL}")
            clear_tool_pending()
            try:
                input(i18n.t("main.press_enter"))
            except (EOFError, KeyboardInterrupt):
                print(f"\n{i18n.t('main.goodbye')}")
                break
        except EOFError:
            print(f"\n{i18n.t('main.goodbye')}")
            break
        except Exception as e:
            print(f"{Fore.RED}{i18n.t('main.error', error=e)}{Style.RESET_ALL}")
            log.error(f"主循环错误: {e}", exc_info=True)
