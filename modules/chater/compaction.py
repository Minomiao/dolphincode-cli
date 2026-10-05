"""上下文整理（compaction）：由 AI 自行决定历史消息的保留、删除与摘要。

流程（三阶段，全部使用无头 AI 调用 chat_ai）：
1. 预检（代码）：按分组粗估可释放 token，低于窗口 COMPACT_MIN_FREED_RATIO 直接放弃；
2. 归档：把完整对话发给无头 AI，仅放行 memory_manager 技能，
   由 AI 自选内容写入项目记忆（Dmemory）；溢出通过归档指令约束（最多 3 条、相近合并）；
3. 决策：以「一次 user 到下一次 user」为一组，AI 输出 keep/delete 组号 JSON，
   未提及的组进入统一摘要；
4. 摘要：未选择组内容生成一段整体摘要；
5. 应用：delete 与摘要组打 _send=False（原文保留在会话 JSON，回显不受影响），
   在第一个摘要组位置插入合成 user 摘要消息（_display=False，只发送不回显）。

前缀复用（提升服务端缓存命中率）：
归档/决策/摘要三次调用都以「项目标准 system + 主对话当前发送列表」为前缀
（reuse_history_prefix=True，并传入 chat.context.prepare_messages 的结果），
与主对话此前请求逐字节一致，因此能命中 DeepSeek 硬盘前缀缓存；三次调用之间
也共享同一前缀，第 2、3 次会命中第 1 次建立的缓存。任务指令仅作为末尾 user 消息追加。

安全约束：
- 最后一组（当前回合）与 system head 永远保护，不参与候选；
- 任何 AI 调用/解析失败都不修改消息，仅通过事件与日志反馈；
- 整理结果随会话 JSON 持久化，load 后仍然生效。
"""

import json

from modules.bootstrap import constants
from modules.core import events
from modules.logger import get_logger

log = get_logger("Dolphin.compaction")

# 三次调用的任务指令存放于 date/prompts/compaction/ 下，由 prompt_manager 加载
# （映射见 prompt_defaults._PROMPT_FILES），作为末尾 user 消息追加、不占用 system，
# 以保留可复用的对话前缀。指令内容参考项目提示词的英文 <tag> 风格。

# 决策/摘要清单的预览参数（完整内容已在历史前缀中，清单只需标识组）
_PREVIEW_PER_MSG = 100
_PREVIEW_TOTAL = 500


def _get_compact_prompt(key: str) -> str:
    """读取上下文整理提示词。

    每次调用都从 prompt_manager 现取，保证运行期编辑提示词文件后立即生效。
    """
    from modules.main_server.prompt_manager import get_prompt_manager
    return get_prompt_manager().get_prompt(key)


def build_groups(messages: list) -> list:
    """把消息列表按「一次 user 到下一次 user」切分为原子组。

    跳过 role=system 的消息与 _send=False 的消息。
    返回 [{"index": 组号, "start": 起始绝对索引, "end": 结束绝对索引(含),
           "messages": [...], "tokens": 估算值}]，按出现顺序编号。
    """
    groups = []
    current = None
    for idx, msg in enumerate(messages):
        if msg.get("role") == "system":
            continue
        if msg.get(constants.MSG_SEND_FIELD) is False:
            continue
        if msg.get("role") == "user":
            if current:
                groups.append(current)
            current = {"start": idx, "end": idx, "messages": [msg]}
        elif current is not None:
            current["end"] = idx
            current["messages"].append(msg)
    if current:
        groups.append(current)

    from modules.chater.context import ContextManager
    estimator = ContextManager(lambda: "")
    for i, g in enumerate(groups):
        g["index"] = i
        g["tokens"] = estimator._estimate_tokens(g["messages"])
    return groups


def _preview(group: dict) -> str:
    """把一组消息压成单行预览（角色 + 内容片段），用于决策/摘要清单标识分组。"""
    parts = []
    for msg in group["messages"]:
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            )
        content = str(content)
        if len(content) > _PREVIEW_PER_MSG:
            content = content[:_PREVIEW_PER_MSG] + "…"
        parts.append(f"[{msg.get('role')}] {content}")
    line = " ".join(parts)
    if len(line) > _PREVIEW_TOTAL:
        line = line[:_PREVIEW_TOTAL] + "…"
    return line


def _manifest(groups: list) -> str:
    """生成分组清单文本：组号 | token 估算 | 预览（与英文提示词的 group 指代一致）。"""
    return "\n".join(
        f"group {g['index']} | ~{g['tokens']} tokens | {_preview(g)}" for g in groups
    )


def _extract_json(text: str) -> dict | None:
    """从模型输出中稳健提取首个 JSON 对象。"""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def _archive(chat, history: list) -> list:
    """阶段 1：完整对话（历史前缀）发给无头 AI，使用 memory_manager 写项目记忆。

    Returns:
        成功写入的记忆 key 列表（可能为空，不阻断流程）
    """
    from modules.functions.ai_caller import chat_ai

    result = await chat_ai(
        prompt=_get_compact_prompt("compaction_archive"),
        history=history,
        allowed_tools=["memory_manager"],
        work_directory=chat.current_work_directory,
        max_tool_rounds=6,
        temperature=0,
        reuse_history_prefix=True,
    )
    keys = []
    for tc in result.get("tool_calls", []):
        if "write_memory" not in tc.get("name", ""):
            continue
        try:
            r = json.loads(tc.get("result", "") or "{}")
            if r.get("success") and r.get("key"):
                keys.append(r["key"])
        except json.JSONDecodeError:
            continue
    log.info(f"归档完成: {len(keys)} 条记忆 {keys}")
    return keys


async def _request_decisions(chat, groups: list, history: list) -> dict | None:
    """阶段 2：AI 逐组选择 keep/delete，未提及的组默认进入摘要。"""
    from modules.functions.ai_caller import chat_ai

    prompt = f"{_get_compact_prompt('compaction_decision')}\n\n<groups>\n{_manifest(groups)}"
    result = await chat_ai(
        prompt=prompt,
        history=history,
        enable_tools=False,
        temperature=0,
        max_tokens=constants.COMPACT_DECISION_MAX_TOKENS,
        reuse_history_prefix=True,
    )
    return _extract_json(result.get("content", ""))


async def _request_summary(chat, groups: list, goal: str, history: list) -> str | None:
    """阶段 3：对指定组生成一条整体摘要。"""
    from modules.functions.ai_caller import chat_ai

    prompt = (
        f"{_get_compact_prompt('compaction_summary')}\n\n"
        f"<groups>\n{_manifest(groups)}\n\n<current_task>\n{goal}"
    )
    result = await chat_ai(
        prompt=prompt,
        history=history,
        enable_tools=False,
        temperature=0.2,
        max_tokens=constants.COMPACT_SUMMARY_MAX_TOKENS,
        reuse_history_prefix=True,
    )
    summary = (result.get("content") or "").strip()
    return summary or None


def _apply(chat, groups: list, decisions: dict, summary: str | None,
           archive_keys: list) -> dict:
    """应用整理结果：打 _send=False 标记并插入摘要消息（_display=False）。

    Returns:
        统计 dict（kept/deleted/summarized 组数与释放 token 估算）
    """
    keep_ids = set(decisions.get("keep") or [])
    delete_ids = set(decisions.get("delete") or [])
    valid_ids = {g["index"] for g in groups}
    keep_ids &= valid_ids
    delete_ids &= valid_ids - keep_ids  # 同时出现以 keep 为准
    summary_ids = valid_ids - keep_ids - delete_ids

    freed = 0
    first_summary_pos = None
    for g in groups:
        if g["index"] in keep_ids:
            continue
        for i in range(g["start"], g["end"] + 1):
            chat.messages[i] = dict(chat.messages[i])
            chat.messages[i][constants.MSG_SEND_FIELD] = False
        freed += g["tokens"]
        if g["index"] in summary_ids and first_summary_pos is None:
            first_summary_pos = g["start"]

    if summary_ids and summary and first_summary_pos is not None:
        keys_line = f"\n\n已归档记忆（可用记忆工具检索）: {', '.join(archive_keys)}" if archive_keys else ""
        content = f"[上下文已整理] {decisions.get('goal', '')}\n\n{summary}{keys_line}"
        chat.messages.insert(first_summary_pos, {
            "role": "user",
            "content": content,
            constants.MSG_DISPLAY_FIELD: False,
        })
        freed -= len(content) // 3  # 摘要自身占用

    return {
        "kept": len(keep_ids),
        "deleted": len(delete_ids),
        "summarized": len(summary_ids),
        "freed_tokens": max(0, freed),
        "archive_keys": archive_keys,
    }


def _append_display_record(chat) -> None:
    """向对话追加一条仅显示、不发送的整理完成记录（历史回显为灰色标签行）。

    _send=False 使其不进入 API 发送列表；user_output 让历史回显按标签行渲染。
    该记录同时被 build_groups 跳过，不参与后续整理。详细统计见日志。
    """
    chat.messages.append({
        "role": "user",
        "content": "",
        constants.MSG_SEND_FIELD: False,
        "user_output": {"label": "Compact", "parts": [{"text": "已完成压缩", "style": "gray"}]},
    })


async def compact_history(chat, auto: bool = False) -> dict | None:
    """整理对话历史：归档 → 决策 keep/delete → 统一摘要 → 应用。

    正式发起 AI 调用前发出 EVENT_CONTEXT_COMPACT_START（UI 显示等待动画），
    结束时无论成功、放弃或失败都发出 EVENT_CONTEXT_COMPACTED 收尾并给出结果。

    Args:
        chat: DolphinChat 实例
        auto: 是否自动触发（仅影响日志文案）

    Returns:
        成功时返回统计 dict；放弃或失败返回 None（不修改任何消息）
    """
    from modules.main_server import config

    groups = build_groups(chat.messages)
    candidates = groups[:-1]  # 保护最后一组（当前回合）
    if len(candidates) < 2:
        log.info("上下文整理跳过：候选分组不足")
        await chat._call_callback(events.EVENT_CONTEXT_COMPACTED, {
            "freed_tokens": 0, "skipped": "对话过短",
        })
        return None

    # 阶段 0：释放量预检（不烧 AI 调用）
    context_window = config.get_context_window(chat.model)
    total = sum(g["tokens"] for g in candidates)
    if total < context_window * constants.COMPACT_MIN_FREED_RATIO:
        log.info(f"上下文整理跳过：可释放 ~{total} token，低于阈值")
        await chat._call_callback(events.EVENT_CONTEXT_COMPACTED, {
            "freed_tokens": 0, "skipped": "可释放内容不足",
        })
        return None

    # 复用主对话当前发送列表作为历史前缀（去掉 system，由无头调用重新取同一静态 system），
    # 三次调用共享此前缀以命中服务端缓存
    history = chat.context.prepare_messages(chat.messages)[1:]

    trigger = "自动" if auto else "手动"
    stats = None
    error = None

    # 通知 UI 进入等待（spinner），与工具调用共用同一等待动画
    await chat._call_callback(
        events.EVENT_CONTEXT_COMPACT_START, {"candidates": len(candidates)}
    )
    try:
        # 阶段 1：归档（完整对话 + memory_manager 技能）
        archive_keys = await _archive(chat, history)

        # 阶段 2：决策 keep/delete
        decisions = await _request_decisions(chat, candidates, history)
        if decisions is None:
            error = "决策输出解析失败"
        else:
            # 阶段 3：未选择组统一摘要
            valid_ids = {g["index"] for g in candidates}
            keep_ids = set(decisions.get("keep") or []) & valid_ids
            delete_ids = (set(decisions.get("delete") or []) & valid_ids) - keep_ids
            summary_ids = valid_ids - keep_ids - delete_ids
            summary = None
            if summary_ids:
                summary_groups = [g for g in candidates if g["index"] in summary_ids]
                summary = await _request_summary(
                    chat, summary_groups, decisions.get("goal", ""), history,
                )
                if summary is None:
                    error = "摘要生成失败"
            if error is None:
                # 应用 + 落盘（含一条仅显示的整理记录）
                stats = _apply(chat, candidates, decisions, summary, archive_keys)
                _append_display_record(chat)
                chat._save_now()
                log.info(
                    f"{trigger}整理完成: 保留 {stats['kept']} 组, 删除 {stats['deleted']} 组, "
                    f"摘要 {stats['summarized']} 组, 释放 ~{stats['freed_tokens']} token"
                )
    except Exception as e:
        error = str(e)
        log.error(f"{trigger}整理失败: {e}", exc_info=True)
    finally:
        # 统一收尾：成功给统计，放弃/失败给原因；UI 据此停止等待动画
        if stats is not None:
            await chat._call_callback(events.EVENT_CONTEXT_COMPACTED, stats)
        else:
            await chat._call_callback(events.EVENT_CONTEXT_COMPACTED, {
                "freed_tokens": 0, "error": error or "已放弃",
            })
    return stats
