"""UI 事件协议：核心层与 UI 层之间的事件契约。

核心层（modules.chater 等）只通过本模块定义的事件与 UI 层通信：
- 核心层通过事件回调推送流式输出与交互请求；
- UI 层（modules.CLIserver 及未来的 GUI 实现）据此实现各自的渲染与交互。

事件分三类：
1. 流式输出：thinking_* / response_* / tool_*，data 携带增量内容；
2. 交互请求：回调返回值即用户响应（见 INTERACTIVE_EVENTS）；
3. 通知：user_output / console_output / context_usage 等，单向推送。

新增事件时必须同步维护 ALL_EVENTS 与 EVENT_DATA_FIELDS，
并通过 tests/unit/test_events.py 校验契约完整性。
"""
from modules.bootstrap import constants

# ===== 流式思考事件 =====
EVENT_THINKING = "thinking"              # 完整思考内容（非流式） {content}
EVENT_THINKING_START = "thinking_start"  # 流式思考开始
EVENT_THINKING_CHUNK = "thinking_chunk"  # 流式思考增量 {content}
EVENT_THINKING_END = "thinking_end"      # 流式思考结束

# ===== 流式回复事件 =====
EVENT_RESPONSE_CHUNK = "response_chunk"  # 流式回复增量 {content}
EVENT_RESPONSE_END = "response_end"      # 流式回复结束

# ===== 工具事件 =====
EVENT_TOOL_START = "tool_start"   # 工具开始执行 {name}
EVENT_TOOL_CALLS = "tool_calls"   # 工具调用列表 {calls: [{name, arguments}]}
EVENT_TOOL_RESULT = "tool_result"  # 工具执行结果 {raw, formatted}

# ===== 交互请求事件（回调返回值即用户响应） =====
EVENT_USER_INPUT_REQUIRED = "user_input_required"    # 返回用户输入字符串
EVENT_CONFIRMATION_REQUIRED = "confirmation_required"  # 返回 'y'/'n'
EVENT_MAX_ITERATIONS_REACHED = constants.EVENT_MAX_ITERATIONS_REACHED  # 返回 'y'/'n'

# ===== 通知事件 =====
EVENT_USER_OUTPUT = "user_output"           # 结构化用户可见输出 {label, parts}
EVENT_OPERATION_CANCELED = "operation_canceled"   # 用户取消了操作
EVENT_OPERATION_CONFIRMED = "operation_confirmed"  # 用户确认了操作
EVENT_CONSOLE_OUTPUT = "console_output"     # 控制台输出 {content, level}
EVENT_CONTEXT_USAGE = "context_usage"       # 上下文用量 {usage_ratio, level}
EVENT_CONTEXT_COMPACT_START = "context_compact_start"  # 上下文整理开始 {candidates}
EVENT_CONTEXT_COMPACTED = "context_compacted"  # 上下文整理结束 {freed_tokens, ...}

# 全部事件集合
ALL_EVENTS = frozenset({
    EVENT_THINKING,
    EVENT_THINKING_START,
    EVENT_THINKING_CHUNK,
    EVENT_THINKING_END,
    EVENT_RESPONSE_CHUNK,
    EVENT_RESPONSE_END,
    EVENT_TOOL_START,
    EVENT_TOOL_CALLS,
    EVENT_TOOL_RESULT,
    EVENT_USER_INPUT_REQUIRED,
    EVENT_CONFIRMATION_REQUIRED,
    EVENT_MAX_ITERATIONS_REACHED,
    EVENT_USER_OUTPUT,
    EVENT_OPERATION_CANCELED,
    EVENT_OPERATION_CONFIRMED,
    EVENT_CONSOLE_OUTPUT,
    EVENT_CONTEXT_USAGE,
    EVENT_CONTEXT_COMPACT_START,
    EVENT_CONTEXT_COMPACTED,
})

# 交互请求事件：回调需要返回值（用户响应），其余事件返回值被忽略
INTERACTIVE_EVENTS = frozenset({
    EVENT_USER_INPUT_REQUIRED,
    EVENT_CONFIRMATION_REQUIRED,
    EVENT_MAX_ITERATIONS_REACHED,
})

# 各事件 data 的必填字段（交互类事件字段均为可选，不在此登记）
EVENT_DATA_FIELDS = {
    EVENT_THINKING: ("content",),
    EVENT_THINKING_CHUNK: ("content",),
    EVENT_RESPONSE_CHUNK: ("content",),
    EVENT_TOOL_START: ("name",),
    EVENT_TOOL_CALLS: ("calls",),
    EVENT_TOOL_RESULT: ("raw",),
    EVENT_USER_OUTPUT: ("parts",),
    EVENT_CONSOLE_OUTPUT: ("content",),
    EVENT_CONTEXT_USAGE: ("usage_ratio",),
    EVENT_CONTEXT_COMPACT_START: ("candidates",),
    EVENT_CONTEXT_COMPACTED: ("freed_tokens",),
    EVENT_MAX_ITERATIONS_REACHED: ("iterations", "hard_limit"),
}


def validate_event(event_type, data):
    """校验事件数据是否符合协议。

    Args:
        event_type: 事件类型
        data: 事件数据字典

    Returns:
        (ok, missing)：是否合法及缺失的必填字段列表；
        未知事件返回 (False, [])
    """
    if event_type not in ALL_EVENTS:
        return False, []
    if data is None:
        data = {}
    missing = [f for f in EVENT_DATA_FIELDS.get(event_type, ()) if f not in data]
    return (not missing), missing
