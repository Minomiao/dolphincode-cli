"""独立的非交互式 AI 调用封装。

供其他模块或技能在不依赖 CLI 交互的前提下发起一次 AI 对话：
- 每次调用创建独立的 DolphinChat 实例，互不共享消息
- 持续执行工具回合直到模型给出最终回复（默认封顶 10 轮），不做多轮迭代确认
- 默认启用技能/插件工具，确认类申请自动拒绝、用户输入取默认值
- 不设置保存目标，不写盘
- 创建实例后恢复全局 AI 临时工作目录，不影响主对话

为避免与 modules.chater 形成循环导入，DolphinChat 在函数体内延迟导入。
"""
from modules.logger import get_logger
from modules.main_server import config
from modules.main_server.middleware import request_manager
from modules.main_server.middleware.request_manager import _run_async
from modules.bootstrap import constants

log = get_logger("Dolphin.ai_caller")


def _headless_callback(event_type, data):
    """非交互式回调：自动决策所有需要用户介入的事件。"""
    if event_type == 'user_input_required':
        return data.get('default_value') or ""
    if event_type in ('confirmation_required', constants.EVENT_MAX_ITERATIONS_REACHED):
        return 'n'
    return None


def _tool_allowed(tool: dict, allowed: list) -> bool:
    """判断工具是否在允许列表中。

    支持完整工具名匹配（如 "stdskill_git"），
    也支持按 `_技能名`/`_函数名` 后缀匹配（如传 "file_manager" 启用该技能全部函数）。
    """
    name = tool.get("function", {}).get("name", "")
    return any(name == item or name.endswith(f"_{item}") for item in allowed)


def _build_result(chat, final_content: str) -> dict:
    """从对话实例组装完整返回结果，供请求方自行处理。"""
    # 去掉内部动态上下文字段，返回干净的对话历史
    messages = [
        {k: v for k, v in m.items() if k != '_context'}
        for m in chat.messages
    ]

    # 提取工具调用记录（名称、参数、执行结果）
    tool_results = {
        m.get("tool_call_id"): m.get("content", "")
        for m in messages if m.get("role") == "tool"
    }
    tool_calls = []
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                tool_calls.append({
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", ""),
                    "result": tool_results.get(tc.get("id"), ""),
                })

    # 各轮思考过程
    reasoning = [
        m.get("reasoning_content")
        for m in messages
        if m.get("role") == "assistant" and m.get("reasoning_content")
    ]

    # 最后一条 assistant 仍带工具调用说明因达到回合上限被截断
    last = messages[-1] if messages else None
    truncated = bool(last and last.get("role") == "assistant" and last.get("tool_calls"))
    rounds = sum(
        1 for m in messages
        if m.get("role") == "assistant" and m.get("tool_calls")
    )

    return {
        "content": final_content,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "messages": messages,
        "usage": chat.context.check_context_usage(
            messages, config.get_context_window(chat.model)
        ),
        "truncated": truncated,
        "rounds": rounds,
    }


async def chat_ai(
    prompt: str,
    *,
    system_prompt: str | None = None,
    history: list | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    effort_level: str = "fine",
    enable_tools: bool = True,
    allowed_tools: list | None = None,
    work_directory: str | None = None,
    max_tool_rounds: int = 10,
) -> dict:
    """发起一次非交互式 AI 对话，返回完整结果 dict。

    工具回合：模型请求工具时执行工具并继续对话，直到模型给出最终文字回复
    或达到 max_tool_rounds 上限，不进入流式的多轮迭代确认流程。

    Args:
        prompt: 本轮用户输入
        system_prompt: 自定义系统提示词（默认使用项目标准系统提示词）
        history: 前置对话历史（不含本轮 prompt），格式与 chat.messages 一致
        temperature: 采样温度
        max_tokens: 最大输出 token 数（默认取配置值）
        effort_level: 思考深度（fine / normal / high）
        enable_tools: 是否启用技能/插件工具（默认开启；确认类申请自动拒绝）
        allowed_tools: 工具白名单，None 表示全部启用；支持完整工具名
            （如 "stdskill_git"）或技能/函数名后缀（如 "file_manager"）
        work_directory: 注入动态上下文的工作目录（不传则不注入）
        max_tool_rounds: 工具回合数上限（避免无限循环）

    Returns:
        dict 完整返回结果，由请求方自行处理：
        - content: 最终回复文本
        - reasoning: 各轮思考过程列表
        - tool_calls: 工具调用记录列表（name / arguments / result）
        - messages: 完整消息历史（含思考过程与工具结果）
        - usage: token 用量统计（含缓存命中、API 调用次数等）
        - truncated: 是否因达到 max_tool_rounds 上限被截断
        - rounds: 实际工具回合数
        API 失败时抛出 OpenAI 异常，由调用方处理
    """
    # 延迟导入，避免与 modules.chater.chat 循环导入
    from modules.chater.chat import DolphinChat
    from modules.chater.context import ContextManager

    saved_work_dir = request_manager.get_ai_work_directory()
    chat = DolphinChat(
        model=config.load_config().get('model', 'deepseek-v4-flash'),
        temperature=temperature,
        max_tokens=max_tokens,
        enable_tools=enable_tools,
        callback=_headless_callback,
    )
    # DolphinChat 初始化会重置全局 AI 临时工作目录，此处恢复主会话的值
    if saved_work_dir is None:
        request_manager.reset_ai_work_directory()
    else:
        request_manager.set_ai_work_directory(saved_work_dir)

    chat.effort_level = effort_level
    # 工具白名单过滤：只保留允许的工具定义
    if allowed_tools is not None:
        chat.tools = [t for t in chat.tools if _tool_allowed(t, allowed_tools)]
        log.debug(f"工具白名单过滤后: {len(chat.tools)} 个工具")
    if work_directory:
        chat.current_work_directory = work_directory

    # 自定义系统提示词或不注入动态上下文时，替换上下文管理器
    if system_prompt or not work_directory:
        chat.context = ContextManager(
            (lambda: system_prompt) if system_prompt else chat.get_system_prompt,
            chat.get_context_prompt if work_directory else None,
        )

    if history:
        chat.messages = list(history)

    final_content = await chat.chat(prompt, max_tool_rounds=max_tool_rounds)
    return _build_result(chat, final_content)


def chat_ai_sync(prompt: str, **kwargs) -> dict:
    """chat_ai 的同步包装，供 skill（线程中同步执行）等场景调用，返回完整结果 dict。"""
    return _run_async(chat_ai(prompt, **kwargs))
