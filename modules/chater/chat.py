import json
import os
import asyncio
import time
import uuid

from openai import OpenAI
from modules.main_server import config
from modules.chater import conversation
from modules.chater.context import ContextManager
from modules.loader import mcp_manager
from modules.loader import skill_manager
from modules.loader import plugin_skill_loader
from modules.loader import standard_skill_loader
from modules.main_server.middleware import request_manager
from modules.functions import backup_manager, powershell_manager
from modules.bootstrap import constants
from modules.logger import get_logger, log_thinking

log = get_logger("Dolphin.chat")

def format_tool_result(result_str):
    """格式化工具返回结果，使其更易读"""
    try:
        result = json.loads(result_str)
        formatted_lines = []
        
        def format_value(key, value, indent=0):
            prefix = "  " * indent
            match value:
                case dict():
                    formatted_lines.append(f"{prefix}{key}:")
                    for k, v in value.items():
                        format_value(k, v, indent + 1)
                case list():
                    formatted_lines.append(f"{prefix}{key}: [{len(value)} 项]")
                    for i, v in enumerate(value):
                        format_value(f"[{i}]", v, indent + 1)
                case str():
                    if '\n' in value:
                        lines = value.strip().split('\n')
                        formatted_lines.append(f"{prefix}{key}:")
                        for line in lines:
                            formatted_lines.append(f"{prefix}  {line}")
                    else:
                        formatted_lines.append(f"{prefix}{key}: {value}")
                case bool():
                    formatted_lines.append(f"{prefix}{key}: {'是' if value else '否'}")
                case None:
                    formatted_lines.append(f"{prefix}{key}: (空)")
                case _:
                    formatted_lines.append(f"{prefix}{key}: {value}")
        
        if isinstance(result, dict):
            for key, value in result.items():
                format_value(key, value)
        else:
            # 处理非字典类型的返回值
            formatted_lines.append(f"result: {result}")
        
        return '\n'.join(formatted_lines)
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_display_name(tool_name: str, skill_mgr=None, plugin_loader=None) -> str:
    """将 tool_name 解析为 'skill.func' 格式的显示名，用于预览。"""
    if tool_name.startswith("skill_"):
        rest = tool_name[6:]
        parts = rest.split("_")
        if skill_mgr:
            for i in range(len(parts), 0, -1):
                possible_skill = "_".join(parts[:i])
                if possible_skill in skill_mgr.skills:
                    func = "_".join(parts[i:])
                    return f"{possible_skill}.{func}"
        return rest
    elif tool_name.startswith("plugin_"):
        rest = tool_name[7:]
        parts = rest.split("_")
        if plugin_loader:
            for i in range(len(parts), 0, -1):
                possible_skill = "_".join(parts[:i])
                if possible_skill in plugin_loader.skills:
                    func = "_".join(parts[i:])
                    return f"{possible_skill}.{func}"
        return rest
    elif tool_name.startswith("stdskill_"):
        return tool_name[len("stdskill_"):]
    else:
        return tool_name


class DolphinChat:
    def __init__(self, model="deepseek-v4-flash", temperature=0.7, max_tokens=None, enable_tools=True, callback=None):
        self.model = model
        self.temperature = temperature
        
        # 缓存配置，避免重复读取文件
        _cfg = config.load_config()
        
        # 从配置中读取 max_tokens，如果没有提供或配置中没有，则使用默认值 18000
        if max_tokens is None:
            max_tokens = _cfg.get('max_tokens', 18000)
        
        self.max_tokens = max_tokens
        self.effort_level = "fine"  # fine / normal / high
        self.messages = []
        self.context = ContextManager(self.get_system_prompt, self.get_context_prompt)
        self.enable_tools = enable_tools
        self.callback = callback or (lambda *args, **kwargs: None)
        self.client = OpenAI(
            api_key=_cfg.get("api_key"),
            base_url=_cfg.get("base_url", "https://api.deepseek.com"),
            timeout=constants.API_TIMEOUT
        )
        self.mcp_mgr = mcp_manager.get_mcp_manager()
        self.skill_mgr = skill_manager.get_skill_manager()
        self.plugin_loader = plugin_skill_loader.get_plugin_skill_loader()
        self.std_loader = standard_skill_loader.get_standard_skill_loader()
        self.request_manager = request_manager.get_request_manager()
        
        self.backup_mgr = backup_manager.get_backup_manager()
        
        # dialog_id = conv_id（在 set_save_target 时统一设置）
        self.dialog_id = None

        self._update_tools()
        self._save_dir_id = None
        self._save_conv_id = None

        # 流式缓冲：生成中的 chunk 先落盘再显示，消息完成后并入 JSON
        self._stream_buffer_path = None
        self._stream_buffer_fh = None
        
        # 工具分发链: (谓词, 处理器) 对
        self._tool_dispatch = [
            (lambda n: n.startswith("skill_"), self.skill_mgr.call_tool),
            (lambda n: n.startswith("plugin_"), self.plugin_loader.call_tool),
            (lambda n: n.startswith("stdskill_"), self.std_loader.call_tool),
            (lambda n: "_" in n, self.mcp_mgr.call_tool),
        ]

        # 确认请求分发链: (谓词, 处理器) 对
        rm_type = request_manager.RequestType
        self._confirmation_dispatch = [
            (lambda d, t: t == rm_type.USER_INPUT, self._handle_user_input_request),
            (lambda d, t: t == rm_type.CONFIRMATION, self._handle_confirmation_request),
            (lambda d, t: d.get("requires_confirmation"), self._handle_requires_confirmation_request),
        ]
        
        # 从配置读取默认工作目录
        self.default_work_directory = _cfg.get('work_directory', 'workplace')
        self.current_work_directory = self.default_work_directory
        request_manager.reset_ai_work_directory()

        log.info(f"初始化 DolphinChat: model={model}, temperature={temperature}, max_tokens={max_tokens}, enable_tools={enable_tools}")
    
    def add_message(self, role, content, tool_calls=None, reasoning_content=None):
        message = {"role": role, "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        if reasoning_content:
            message["reasoning_content"] = reasoning_content
        self.messages.append(message)
        log.debug(f"添加消息: role={role}, content_length={len(content)}, tool_calls={len(tool_calls) if tool_calls else 0}")
        self._save_now()

    def _save_now(self):
        """立即同步写盘：每条完整消息生成后先落盘，再进入显示流程。

        主循环会阻塞在 input()，事件循环不再有机会执行异步保存任务，
        因此对话保存统一采用同步写盘，保证"先储存后显示"。
        """
        if not (self._save_dir_id and self._save_conv_id):
            return
        conversation.save_conversation(list(self.messages), self._save_dir_id, self._save_conv_id)

    def _open_stream_buffer(self):
        """打开流式缓冲文件（追加模式）。"""
        if self._stream_buffer_fh is not None:
            return
        if not (self._save_dir_id and self._save_conv_id):
            return
        conv_folder = os.path.join(conversation.CONVERSATIONS_DIR, self._save_dir_id, self._save_conv_id)
        os.makedirs(conv_folder, exist_ok=True)
        self._stream_buffer_path = os.path.join(conv_folder, "stream.jsonl")
        self._stream_buffer_fh = open(self._stream_buffer_path, 'a', encoding='utf-8')

    def _append_stream_chunk(self, kind, text):
        """先储存后显示：将流式块同步追加到缓冲文件并刷新。"""
        if not text:
            return
        if self._stream_buffer_fh is None:
            self._open_stream_buffer()
        if self._stream_buffer_fh is None:
            return
        try:
            self._stream_buffer_fh.write(json.dumps({"t": kind, "c": text}, ensure_ascii=False) + "\n")
            self._stream_buffer_fh.flush()
        except Exception as e:
            log.warning(f"写入流式缓冲失败: {e}")

    def _clear_stream_buffer(self):
        """消息已并入 JSON 后清空缓冲文件，避免下次恢复时重复合并。"""
        if self._stream_buffer_fh is not None:
            try:
                self._stream_buffer_fh.close()
            except Exception:
                pass
            self._stream_buffer_fh = None
        if self._stream_buffer_path and os.path.exists(self._stream_buffer_path):
            try:
                os.remove(self._stream_buffer_path)
            except Exception as e:
                log.debug(f"删除流式缓冲失败: {e}")
        self._stream_buffer_path = None

    def _recover_stream_buffer(self, messages, dir_id, conv_id):
        """将崩溃/退出时遗留的流式缓冲恢复为一条部分 assistant 消息。

        内容块和思考块分别拼回 content 与 reasoning_content，
        恢复后立即写盘并删除缓冲文件，保证"显示过的内容不丢失"。
        """
        path = os.path.join(conversation.CONVERSATIONS_DIR, dir_id, conv_id, "stream.jsonl")
        if not os.path.exists(path):
            return messages

        content_parts = []
        reasoning_parts = []
        if messages is None:
            messages = []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = entry.get("t")
                    text = entry.get("c", "")
                    if kind == "thinking":
                        reasoning_parts.append(text)
                    elif kind == "content":
                        content_parts.append(text)
        except Exception as e:
            log.warning(f"读取流式缓冲失败: {e}")
            return messages

        if not content_parts and not reasoning_parts:
            # 空缓冲文件，直接清理
            try:
                os.remove(path)
            except Exception as e:
                log.debug(f"删除流式缓冲失败: {e}")
            return messages

        recovered_content = "".join(content_parts)
        recovered_reasoning = "".join(reasoning_parts)
        # 去重：若缓冲与最后一条已提交的 assistant 消息完全一致，
        # 说明内容已随消息落盘（崩溃发生在保存后、清缓冲前），直接清理避免重复。
        if messages and messages[-1].get("role") == "assistant":
            last = messages[-1]
            if (last.get("content", "") == recovered_content
                    and last.get("reasoning_content", "") == recovered_reasoning):
                try:
                    os.remove(path)
                except Exception as e:
                    log.debug(f"删除流式缓冲失败: {e}")
                return messages

        recovered = {"role": "assistant", "content": recovered_content}
        if recovered_reasoning:
            recovered["reasoning_content"] = recovered_reasoning
        messages.append(recovered)
        log.warning(
            f"对话恢复: 从流式缓冲恢复内容 {len(content_parts)} 块, 思考 {len(reasoning_parts)} 块"
        )
        # 先写盘成功再删除缓冲，避免保存失败导致内容丢失
        conversation.save_conversation(list(messages), dir_id, conv_id)
        try:
            os.remove(path)
        except Exception as e:
            log.debug(f"删除流式缓冲失败: {e}")
        return messages

    def save_on_exit(self, dir_id, conv_id):
        """退出兜底：合并流式缓冲残留并同步写盘。"""
        self._save_dir_id = dir_id
        self._save_conv_id = conv_id
        recovered = self._recover_stream_buffer(list(self.messages), dir_id, conv_id)
        if recovered is not self.messages:
            self.messages = recovered
        conversation.save_conversation(list(self.messages), dir_id, conv_id)
        self._clear_stream_buffer()

    def _merge_stale_stream_buffer(self):
        """将上一轮异常中断遗留的流式缓冲并入消息后清理。

        流式中途被中断时缓冲文件可能残留且句柄未关，若直接复用会导致
        新旧 chunk 混入同一文件。每轮开始前先合并残留，保证已显示内容不丢失。
        """
        if self._stream_buffer_fh is None and not (
            self._stream_buffer_path and os.path.exists(self._stream_buffer_path)
        ):
            return
        if not (self._save_dir_id and self._save_conv_id):
            return
        self._recover_stream_buffer(self.messages, self._save_dir_id, self._save_conv_id)
        self._clear_stream_buffer()

    def set_save_target(self, dir_id, conv_id):
        self._save_dir_id = dir_id
        self._save_conv_id = conv_id
        # dialog_id = conv_id（统一标识）
        self.dialog_id = conv_id
        # 同步设置备份管理器的会话上下文
        if self.backup_mgr:
            self.backup_mgr.set_session(dir_id, conv_id)
        log.debug(f"设置保存目标: dir={dir_id}, conv={conv_id}, dialog_id={conv_id}")

    def _update_tools(self):
        self.tools = []
        if self.enable_tools:
            skill_tools = self.skill_mgr.get_all_tools()
            self.tools.extend(skill_tools)
            
            # 添加插件技能工具
            plugin_tools = self.plugin_loader.get_all_tools()
            self.tools.extend(plugin_tools)

            # 添加标准技能工具
            std_tools = self.std_loader.get_all_tools()
            self.tools.extend(std_tools)
        log.debug(f"更新工具列表: 共 {len(self.tools)} 个工具")
    
    def reset_work_directory(self):
        """重置工作目录到默认配置"""
        self.current_work_directory = self.default_work_directory
        request_manager.reset_ai_work_directory()
        log.info(f"工作目录已重置为: {self.current_work_directory}")
    
    def get_system_prompt(self) -> str:
        """获取静态系统提示词（仅行为规则，用于 prompt caching）"""
        prompt_request = self.request_manager.create_prompt_request("system")
        result = self.request_manager.handle_request(prompt_request, None)

        if result.get("success"):
            return result.get("prompt", "")

        log.warning("PromptManager 获取系统提示词失败，使用最小化 fallback")
        return "你是一个AI助手。"

    def get_context_prompt(self) -> str:
        """获取每轮动态上下文（工作目录 + 目录结构 + 努力程度）"""
        prompt_request = self.request_manager.create_prompt_request(
            "context",
            work_directory=self.current_work_directory,
            directory_structure=self.get_directory_structure(),
            effort_level=self.effort_level
        )
        result = self.request_manager.handle_request(prompt_request, None)

        if result.get("success"):
            return result.get("prompt", "")

        log.warning("PromptManager 获取上下文提示词失败，使用最小化 fallback")
        return f"当前工作目录：{self.current_work_directory}。"
    
    def get_directory_structure(self) -> str:
        """获取当前工作目录的目录结构"""
        try:
            from skills.file_reader.skill import list_directory
            from modules.loader.skill_context import create_default_context
            ctx = create_default_context(self.current_work_directory)
            result = list_directory(ctx, ".", max_depth=3, show_hidden=False)
            if result.get("success"):
                return result.get("tree", "")
            else:
                log.warning(f"list_directory 失败: {result.get('error', 'unknown')}")
                return "无法获取目录结构"
        except Exception as e:
            log.error(f"获取目录结构失败: {e}")
            return "无法获取目录结构"
    
    async def _check_context_usage(self):
        """在每轮对话结束后检查上下文用量，通过回调通知。"""
        context_window = config.get_context_window(self.model)
        usage = self.context.check_context_usage(self.messages, context_window)
        # 每轮都发送 usage 信息（不再只在告警时发送）
        await self._call_callback("context_usage", usage)
    
    async def _call_callback(self, event_type, data):
        """调用回调函数，支持同步和异步回调"""
        try:
            if asyncio.iscoroutinefunction(self.callback):
                result = await self.callback(event_type, data)
                return result
            else:
                result = self.callback(event_type, data)
                if event_type == 'tool_start':
                    await asyncio.sleep(0)
                return result
        except Exception as e:
            log.error(f"回调函数执行失败: {e}")
            return None
    
    async def _execute_tool(self, tool_name: str, arguments: dict) -> tuple:
        """执行工具，返回 (result_str, had_user_output, user_output)。"""
        log.info(f"执行工具: {tool_name}, 参数: {arguments}")
        start = time.perf_counter()
        had_user_output = False
        user_output = None
        try:
            for check, handler in self._tool_dispatch:
                if check(tool_name):
                    result = await handler(tool_name, arguments)
                    break
            else:
                result = {"error": f"未知的工具: {tool_name}"}

            # 使用请求管理器处理申请
            if self.request_manager and isinstance(result, dict):
                if self.request_manager.is_request(result):
                    log.debug(f"检测到申请: {result.get('type', 'unknown')}")
                    self.request_manager.handle_request(result, self.callback)

            # 从工具返回结果中直接提取 user_output（显式传递，不再依赖 request_manager 隐式状态）
            if isinstance(result, dict) and result.get("user_output"):
                uo = result.pop("user_output")
                if isinstance(uo, dict):
                    await self._call_callback('user_output', uo)
                else:
                    await self._call_callback('user_output', {'content': str(uo)})
                had_user_output = True
                user_output = uo

            if isinstance(result, dict):
                # 拦截 set_work_directory 成功结果，同步更新 AI 临时工作目录
                if result.get("success") and "set_work_directory" in tool_name and result.get("work_directory"):
                    self.current_work_directory = result["work_directory"]
                    request_manager.set_ai_work_directory(result["work_directory"])
                    self.skill_mgr.set_work_dir(result["work_directory"])
                    log.info(f"AI 临时工作目录已更新: {self.current_work_directory}")
                result_str = json.dumps(result, ensure_ascii=False)
            else:
                result_str = str(result)
            elapsed = time.perf_counter() - start
            log.debug(f"工具执行完成: {tool_name}, 耗时={elapsed:.3f}s, 结果长度={len(result_str)}")
            return result_str, had_user_output, user_output
        except Exception as e:
            elapsed = time.perf_counter() - start
            error_msg = json.dumps({"error": str(e)}, ensure_ascii=False)
            log.error(f"工具执行失败: {tool_name}, 耗时={elapsed:.3f}s, 错误: {str(e)}")
            return error_msg, False, None
    
    async def _execute_powershell_script(self, script: str, timeout: int = 30, wait_time: int = 10) -> dict:
        return await powershell_manager.execute_script(script, timeout, wait_time)

    async def _handle_auto_execute(self, result_dict: dict) -> tuple:
        """处理 auto_execute 请求，直接执行 PowerShell 脚本"""
        ps_timeout = result_dict.get('timeout', 30)
        ps_wait = result_dict.get('wait_time', 10)
        ps_result = await self._execute_powershell_script(result_dict['script'], ps_timeout, ps_wait)
        return json.dumps(ps_result, ensure_ascii=False), False, None

    async def _handle_user_input_request(self, result_dict: dict, tool_name: str, arguments: dict) -> tuple:
        """处理 USER_INPUT 类型的请求"""
        input_data = {
            'prompt': result_dict.get('prompt'),
            'input_type': result_dict.get('input_type'),
            'default_value': result_dict.get('default_value')
        }
        user_input = await self._call_callback('user_input_required', input_data)
        user_out_data = {'label': 'Input', 'parts': [
            {"text": result_dict.get('prompt', '')},
            {"text": user_input, "style": "gray"}
        ]}
        await self._call_callback('user_output', user_out_data)
        return json.dumps({"success": True, "input": user_input}, ensure_ascii=False), False, user_out_data

    async def _handle_confirmation_request(self, result_dict: dict, tool_name: str, arguments: dict) -> tuple:
        """处理 CONFIRMATION 类型的请求"""
        confirmation_data = {
            'action': result_dict.get('action'),
            'default': result_dict.get('default')
        }
        confirm = await self._call_callback('confirmation_required', confirmation_data)
        status_style = "green" if confirm == 'y' else "red"
        status_text = "已确认" if confirm == 'y' else "已取消"
        user_out_data = {'label': 'Confirm', 'parts': [
            {"text": result_dict.get('action', 'unknown')},
            {"text": status_text, "style": status_style}
        ]}
        await self._call_callback('user_output', user_out_data)
        return json.dumps({"success": True, "confirmed": confirm == 'y'}, ensure_ascii=False), False, user_out_data

    async def _handle_requires_confirmation_request(self, result_dict: dict, tool_name: str, arguments: dict) -> tuple:
        """处理 requires_confirmation 类型的请求"""
        confirmation_data = {
            'action': result_dict.get('action', 'unknown'),
            'script_preview': result_dict.get('script_preview'),
            'script': result_dict.get('script'),
            'file_path': result_dict.get('file_path'),
            'work_directory': result_dict.get('work_directory'),
            'error': result_dict.get('error')
        }
        confirm = await self._call_callback('confirmation_required', confirmation_data)

        if confirm != 'y':
            log.info(f"用户取消操作: {tool_name}")
            await self._call_callback('operation_canceled', {})
            return json.dumps({"error": "用户取消操作"}, ensure_ascii=False), True, None

        log.info(f"用户确认操作: {tool_name}")
        await self._call_callback('operation_confirmed', {})

        if result_dict.get('action') == 'run_powershell_script' and result_dict.get('script'):
            ps_timeout = result_dict.get('timeout', 30)
            ps_wait = result_dict.get('wait_time', 10)
            ps_result = await self._execute_powershell_script(result_dict['script'], ps_timeout, ps_wait)
            return json.dumps(ps_result, ensure_ascii=False), False, None

        if isinstance(arguments, dict):
            arguments['confirmed'] = True
        else:
            arguments = {'confirmed': True}
        result_str, _, reexec_uo = await self._execute_tool(tool_name, arguments)
        return result_str, False, reexec_uo

    async def _process_tool_confirmation(self, result_raw: str, tool_name: str, arguments: dict):
        """处理工具返回的确认申请，返回 (result_str, should_skip, user_output)"""
        try:
            result_dict = json.loads(result_raw)
        except (json.JSONDecodeError, TypeError):
            return result_raw, False, None

        if result_dict.get('auto_execute') and result_dict.get('script'):
            return await self._handle_auto_execute(result_dict)

        if not self.request_manager or not self.request_manager.is_request(result_dict):
            return result_raw, False, None

        request_type = result_dict.get('type')

        for check, handler in self._confirmation_dispatch:
            if check(result_dict, request_type):
                return await handler(result_dict, tool_name, arguments)

        return result_raw, False, None

    async def _run_tool_calls(self, tool_calls: list) -> list:
        """统一执行一批 tool_calls，返回生成的 tool 角色消息列表。"""
        start = time.perf_counter()
        tool_responses = []
        displayed_calls = []
        displayed_results = []

        for tc in tool_calls:
            tool_name = tc['function']['name']
            arguments_str = tc['function'].get('arguments', '{}')

            try:
                arguments = json.loads(arguments_str)
            except (json.JSONDecodeError, TypeError) as e:
                log.error(f"JSON解析失败: {tool_name}, 错误: {str(e)}")
                error_result = {
                    "error": "工具调用参数解析失败",
                    "tool_name": tool_name,
                    "reason": "参数可能被截断或格式错误",
                    "details": str(e),
                    "suggestion": "请尝试重新表述您的需求，或者减少单次操作的复杂度"
                }
                tool_responses.append({
                    "tool_call_id": tc['id'],
                    "role": "tool",
                    "content": json.dumps(error_result, ensure_ascii=False)
                })
                continue

            display_name = _parse_display_name(tool_name, self.skill_mgr, self.plugin_loader)
            await self._call_callback('tool_start', {'name': display_name})

            result, _, skill_uo = await self._execute_tool(tool_name, arguments)
            result, skip, conf_uo = await self._process_tool_confirmation(result, tool_name, arguments)

            final_uo = skill_uo if skill_uo is not None else conf_uo
            has_user_output = final_uo is not None

            entry = {
                "tool_call_id": tc['id'],
                "role": "tool",
                "content": result
            }
            if final_uo is not None:
                entry["user_output"] = final_uo
            tool_responses.append(entry)

            if skip:
                continue

            if not has_user_output:
                displayed_calls.append(tc)
                displayed_results.append((result, format_tool_result(result)))

        self.messages.extend(tool_responses)
        # 先储存：整批工具结果落盘后再显示
        self._save_now()

        if displayed_calls:
            await self._call_callback('tool_calls', {
                'calls': [
                    {
                        'name': tc['function']['name'],
                        'arguments': tc['function'].get('arguments', '')
                    }
                    for tc in displayed_calls
                ]
            })
            for raw, formatted in displayed_results:
                await self._call_callback('tool_result', {
                    'raw': raw,
                    'formatted': formatted
                })

        elapsed = time.perf_counter() - start
        log.info(f"工具调用批次完成: {len(tool_calls)} 个, 耗时={elapsed:.3f}s")
        return tool_responses

    def _apply_effort_params(self, kwargs):
        """根据 effort_level 添加 thinking mode 参数。normal 不传参。"""
        if self.effort_level == "normal":
            return
        effort_map = {"fine": "high", "high": "max"}
        kwargs["reasoning_effort"] = effort_map.get(self.effort_level, "high")
        kwargs.setdefault("extra_body", {})
        kwargs["extra_body"]["thinking"] = {"type": "enabled"}

    async def chat(self, user_input):
        log.info(f"开始聊天 (非流式): 输入长度={len(user_input)}")
        chat_start = time.perf_counter()

        # 先处理上一轮异常中断遗留的流式缓冲，再开始新一轮
        self._merge_stale_stream_buffer()
        self.add_message("user", user_input)
        
        kwargs = {
            "model": self.model,
            "messages": self.context.prepare_messages(self.messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        if self.tools:
            kwargs["tools"] = self.tools
        
        self._apply_effort_params(kwargs)
        
        api_start = time.perf_counter()
        response = self.client.chat.completions.create(**kwargs)
        api_elapsed = time.perf_counter() - api_start
        log.info(f"API 调用完成 (非流式): 耗时={api_elapsed:.3f}s")
        # 保存 API 返回的精确 token 用量
        if hasattr(response, 'usage') and response.usage:
            self.context.update_usage_from_api(response.usage)
        assistant_message = response.choices[0].message
        
        reasoning = None
        if hasattr(assistant_message, 'model_extra') and assistant_message.model_extra:
            reasoning = assistant_message.model_extra.get('reasoning_content')
        
        if reasoning:
            log.debug(f"思考过程长度: {len(reasoning)}")
            log_thinking(reasoning)
            await self._call_callback('thinking', {
                'content': reasoning
            })
        
        tool_calls = assistant_message.tool_calls
        
        if tool_calls:
            log.info(f"检测到 {len(tool_calls)} 个工具调用")
            tool_calls_list = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in tool_calls
            ]
            self.add_message("assistant", assistant_message.content or "", tool_calls_list, reasoning_content=reasoning)

            await self._run_tool_calls(tool_calls_list)

            kwargs["messages"] = self.context.prepare_messages(self.messages)
            api_start = time.perf_counter()
            response = self.client.chat.completions.create(**kwargs)
            api_elapsed = time.perf_counter() - api_start
            log.info(f"API 调用完成 (非流式, 工具后): 耗时={api_elapsed:.3f}s")
            # 保存 API 返回的精确 token 用量
            if hasattr(response, 'usage') and response.usage:
                self.context.update_usage_from_api(response.usage)
            assistant_message = response.choices[0].message

        final_content = assistant_message.content or ""
        total_elapsed = time.perf_counter() - chat_start
        log.info(f"聊天完成: 响应长度={len(final_content)}, 总耗时={total_elapsed:.3f}s")
        self.add_message("assistant", final_content)

        # 新架构：无需清理内存缓存（持久化存储）
        log.debug("对话完成（备份记录已持久化）")

        await self._check_context_usage()

        return final_content
    
    async def _process_stream(self, stream):
        full_response = ""
        full_reasoning = ""
        tool_calls_buffer = {}
        reasoning_started = False
        has_tool_calls = False
        response_started = False
        last_usage = None  # 捕获流式响应的 usage

        try:
            for chunk in stream:
                # 检查 usage 信息（流式响应的最后一块可能包含 usage）
                if hasattr(chunk, 'usage') and chunk.usage:
                    last_usage = chunk.usage

                # usage-only chunk 没有 choices，跳过
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                if hasattr(delta, 'model_extra') and delta.model_extra:
                    reasoning = delta.model_extra.get('reasoning_content')
                    if reasoning:
                        if not reasoning_started:
                            await self._call_callback('thinking_start', {})
                            reasoning_started = True
                        full_reasoning += reasoning
                        # 先储存后显示：思考块先写入流式缓冲
                        self._append_stream_chunk("thinking", reasoning)
                        await self._call_callback('thinking_chunk', {
                            'content': reasoning
                        })

                if delta.content:
                    content = delta.content
                    full_response += content
                    if not response_started:
                        response_started = True
                        if reasoning_started:
                            await self._call_callback('thinking_end', {})
                            reasoning_started = False
                    # 先储存后显示：内容块先写入流式缓冲
                    self._append_stream_chunk("content", content)
                    await self._call_callback('response_chunk', {
                        'content': content
                    })

                if delta.tool_calls:
                    has_tool_calls = True
                    for tc in delta.tool_calls:
                        if tc.index not in tool_calls_buffer:
                            tool_calls_buffer[tc.index] = {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name if tc.function.name else "",
                                    "arguments": tc.function.arguments if tc.function.arguments else ""
                                }
                            }
                        else:
                            if tc.function.name:
                                tool_calls_buffer[tc.index]["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_buffer[tc.index]["function"]["arguments"] += tc.function.arguments
        finally:
            # 确保流式连接被释放，避免中途异常时连接泄漏
            stream.close()

        if reasoning_started:
            log.debug(f"思考过程长度: {len(full_reasoning)}")
            await self._call_callback('thinking_end', {})

        if response_started:
            await self._call_callback('response_end', {})

        return full_response, full_reasoning, tool_calls_buffer, has_tool_calls, last_usage

    async def chat_stream(self, user_input):
        log.info(f"开始聊天 (流式): 输入长度={len(user_input)}")
        chat_start = time.perf_counter()

        # 先处理上一轮异常中断遗留的流式缓冲，再开始新一轮
        self._merge_stale_stream_buffer()
        self.add_message("user", user_input)
        
        kwargs = {
            "model": self.model,
            "messages": self.context.prepare_messages(self.messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True}  # 请求 API 返回 token 用量
        }
        
        if self.tools:
            kwargs["tools"] = self.tools
        
        self._apply_effort_params(kwargs)
        
        api_start = time.perf_counter()
        stream = self.client.chat.completions.create(**kwargs)
        full_response, full_reasoning, tool_calls_buffer, has_tool_calls, last_usage = await self._process_stream(stream)
        api_elapsed = time.perf_counter() - api_start
        log.info(f"API 流式调用完成: 耗时={api_elapsed:.3f}s")

        # 保存 API 返回的精确 token 用量
        if last_usage:
            self.context.update_usage_from_api(last_usage)

        if full_reasoning:
            log_thinking(full_reasoning)

        if not has_tool_calls:
            self.add_message("assistant", full_response, reasoning_content=full_reasoning)
            self._clear_stream_buffer()
        
        if has_tool_calls and tool_calls_buffer:
            tool_calls = list(tool_calls_buffer.values())
            log.info(f"检测到 {len(tool_calls)} 个工具调用")
            self.add_message("assistant", full_response or "", tool_calls, reasoning_content=full_reasoning)
            self._clear_stream_buffer()

            await self._run_tool_calls(tool_calls)

            MAX_HARD_LIMIT = 100
            INITIAL_MAX = 30
            EXTEND_BY = 20

            max_iterations = INITIAL_MAX
            iteration = 1

            while iteration < min(max_iterations, MAX_HARD_LIMIT):
                iteration += 1
                log.debug(f"工具调用迭代 {iteration}/{max_iterations} (hard limit: {MAX_HARD_LIMIT})")

                kwargs["messages"] = self.context.prepare_messages(self.messages)
                kwargs["stream"] = True
                stream = self.client.chat.completions.create(**kwargs)

                full_response, full_reasoning, tool_calls_buffer, has_tool_calls, last_usage = await self._process_stream(stream)

                # 保存 API 返回的精确 token 用量
                if last_usage:
                    self.context.update_usage_from_api(last_usage)

                if full_reasoning:
                    log_thinking(f"[迭代 {iteration}] {full_reasoning}")
                if has_tool_calls and tool_calls_buffer:
                    tool_calls = list(tool_calls_buffer.values())
                    log.info(f"迭代 {iteration}: 检测到 {len(tool_calls)} 个工具调用")
                    self.add_message("assistant", full_response or "", tool_calls, reasoning_content=full_reasoning)
                    self._clear_stream_buffer()

                    await self._run_tool_calls(tool_calls)

                    if iteration >= max_iterations:
                        if iteration >= MAX_HARD_LIMIT:
                            break
                        log.info(f"达到当前迭代上限 {max_iterations}，询问用户是否继续")
                        result = await self._call_callback('max_iterations_reached', {
                            'iterations': iteration,
                            'max_iterations': max_iterations,
                            'hard_limit': MAX_HARD_LIMIT
                        })
                        if result == 'y':
                            max_iterations = min(max_iterations + EXTEND_BY, MAX_HARD_LIMIT)
                            log.info(f"用户确认续期，新上限: {max_iterations}")
                            continue
                        else:
                            log.info("用户选择不继续迭代")
                            break
                    continue
                else:
                    self.add_message("assistant", full_response, reasoning_content=full_reasoning)
                    self._clear_stream_buffer()
                    break

        # 缓冲应已在上一条消息提交后清空，此处兜底清理
        self._clear_stream_buffer()

        # 新架构：无需清理内存缓存（持久化存储）
        log.debug("流式对话完成（备份记录已持久化）")

        await self._check_context_usage()

        total_elapsed = time.perf_counter() - chat_start
        log.info(f"流式聊天完成: 响应长度={len(full_response)}, 总耗时={total_elapsed:.3f}s")
        return full_response
    
    def clear_history(self):
        self.messages = []
        self.context.reset_usage()  # 重置 token 用量统计
        self.reset_work_directory()
        # 显式清空历史时应一并丢弃残留的流式缓冲
        self._clear_stream_buffer()
        # 新架构：无需清理内存缓存（持久化存储）
        log.debug("历史已清空（备份记录已持久化）")
    
    def save_conversation(self, dir_id, conv_id):
        conversation.save_conversation(self.messages, dir_id, conv_id)

    def load_conversation(self, dir_id, conv_id):
        messages = conversation.load_conversation(dir_id, conv_id)
        # 无论 JSON 是否为空/损坏，都先尝试恢复上次强杀遗留的流式缓冲
        # （显示过但未完成的消息），避免损坏文件导致半截回复一并丢失
        messages = self._recover_stream_buffer(messages, dir_id, conv_id)
        if messages:
            messages = conversation.repair_conversation_messages(
                messages, work_dir=self.default_work_directory
            )
            self.messages = messages
            self.reset_work_directory()
            return True
        return False
    
    def list_available_tools(self):
        if not self.enable_tools:
            return []
        
        tools_info = []
        for tool in self.tools:
            tool_name = tool["function"]["name"]
            tool_desc = tool["function"]["description"]
            tools_info.append({
                "name": tool_name,
                "description": tool_desc
            })
        return tools_info
    
    def enable_tool(self, enabled: bool):
        self.enable_tools = enabled
        self._update_tools()
    
    def list_skills(self):
        # 合并普通技能、插件技能和标准技能
        skills = self.skill_mgr.list_skills()
        plugin_skills = self.plugin_loader.list_skills()
        skills.extend(plugin_skills)
        std_skills = self.std_loader.list_skills()
        skills.extend(std_skills)
        return skills
