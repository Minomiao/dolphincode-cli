import os
import json
import time
from modules.logger import get_logger
from modules import bootstrap as app_paths
from modules.bootstrap import constants

log = get_logger("Dolphin.conversation")

CONVERSATIONS_DIR = app_paths.CONVERSATIONS_DIR

_FILE_AUTOCOMPLETE_TOOLS = constants.FILE_AUTOCOMPLETE_TOOLS


def _is_file_tool(tool_name):
    return any(kw in tool_name for kw in _FILE_AUTOCOMPLETE_TOOLS)


def _try_auto_complete_tool(tool_name, arguments, work_dir):
    file_path = arguments.get("file_path", "")
    if not file_path or not work_dir:
        return None

    full_path = os.path.join(work_dir, file_path)
    file_exists = os.path.isfile(full_path)

    if "create_file" in tool_name or "write_file" in tool_name:
        if file_exists:
            try:
                size = os.path.getsize(full_path)
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                limit = constants.RECOVERY_WRITE_PREVIEW_LINES
                total = len(lines)
                if total > limit:
                    lines = lines[:limit]
                preview = "".join(lines)
                result = {
                    "success": True,
                    "file_path": file_path,
                    "size": size,
                    "total_lines": total,
                    "content_preview": preview,
                    "message": f"文件 {file_path} 创建/写入成功 ({size} 字节)",
                    "_recovered": True,
                    "_note": "此结果为对话恢复时自动补全，文件已存在"
                }
                if total > limit:
                    result["content_preview_note"] = f"仅显示前{limit}行，共{total}行"
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                log.debug(f"对话恢复写入文件失败: {file_path}, {e}")
        return json.dumps({
            "success": True,
            "file_path": file_path,
            "message": f"文件 {file_path} 创建请求已记录",
            "_recovered": True,
            "_note": "此结果为对话恢复时自动补全，文件状态未知"
        }, ensure_ascii=False)

    if "read_file" in tool_name:
        if file_exists:
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                total = len(lines)
                limit = constants.RECOVERY_READ_LIMIT_LINES
                if total > limit:
                    lines = lines[:limit]
                content = "".join(lines)
                result = {
                    "success": True,
                    "file_path": file_path,
                    "content": content,
                    "total_lines": total,
                    "_recovered": True,
                    "_note": "此结果为对话恢复时从当前文件状态补全"
                }
                if total > limit:
                    result["content_note"] = f"仅显示前{limit}行，共{total}行"
                return json.dumps(result, ensure_ascii=False)
            except Exception as e:
                log.debug(f"对话恢复读取文件失败: {file_path}, {e}")
        return json.dumps({
            "error": f"文件不存在: {file_path}",
            "file_path": file_path,
            "_recovered": True,
            "_note": "此结果为对话恢复时自动补全"
        }, ensure_ascii=False)

    if "modify_file" in tool_name:
        if file_exists:
            try:
                size = os.path.getsize(full_path)
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                preview = "".join(lines[:30]) if lines else ""
                return json.dumps({
                    "success": True,
                    "file_path": file_path,
                    "size": size,
                    "total_lines": len(lines),
                    "content_preview": preview,
                    "message": f"文件 {file_path} 修改成功 ({size} 字节, {len(lines)} 行)",
                    "_recovered": True,
                    "_note": "此结果为对话恢复时从当前文件状态补全，修改可能已应用"
                }, ensure_ascii=False)
            except Exception as e:
                log.debug(f"对话恢复修改文件失败: {file_path}, {e}")
        return json.dumps({
            "error": f"文件不存在: {file_path}",
            "_recovered": True,
            "_note": "此结果为对话恢复时自动补全"
        }, ensure_ascii=False)

    if "delete_file" in tool_name:
        if not file_exists:
            return json.dumps({
                "success": True,
                "file_path": file_path,
                "message": f"文件 {file_path} 不存在（可能已被删除）",
                "_recovered": True,
                "_note": "此结果为对话恢复时自动补全"
            }, ensure_ascii=False)
        return json.dumps({
            "error": f"文件 {file_path} 仍然存在（删除操作可能未执行）",
            "_recovered": True,
            "_note": "此结果为对话恢复时自动补全"
        }, ensure_ascii=False)

    return None


def _build_interrupted_response(tool_name, arguments):
    return json.dumps({
        "error": (
            f"对话在上次工具调用时意外中断，原始执行结果已丢失。"
            f"工具: {tool_name}，参数: {json.dumps(arguments, ensure_ascii=False)}。"
            f"请根据上下文重新评估当前状态，如有需要请重新执行此操作。"
        ),
        "_recovered": True,
        "_interrupted": True
    }, ensure_ascii=False)


def _build_recovered_user_output(tool_name, arguments):
    """为恢复补全的工具消息生成简约 user_output 标签。

    让历史回显走精简标签而非冗长 JSON 结果：
    - 文件类工具标记 "Recovered"（结果由当前磁盘状态推断）
    - 其余工具标记 "Interrupted"（原始结果已丢失，需 AI 重新评估）
    """
    file_path = arguments.get("file_path", "")
    filename = os.path.basename(file_path) if file_path else (tool_name or "?")

    if "read_file" in tool_name:
        return {"label": "Read", "parts": [
            {"text": f"--{file_path or '?'}"},
            {"text": "Recovered", "style": "yellow"},
        ]}

    if "delete_file" in tool_name:
        return {"label": "File Change", "parts": [
            {"text": f"--{filename}"},
            {"text": "Recovered", "style": "yellow"},
        ]}

    if _is_file_tool(tool_name):
        return {"label": "File Change", "parts": [
            {"text": filename},
            {"text": "Recovered", "style": "yellow"},
        ]}

    return {"label": "Recovered", "parts": [
        {"text": tool_name or "?"},
        {"text": "Interrupted", "style": "red"},
    ]}


def repair_conversation_messages(messages, work_dir=None):
    repaired = []
    repaired_count = 0

    for i, msg in enumerate(messages):
        repaired.append(msg)

        if msg.get("role") != "assistant":
            continue

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue

        tool_ids_with_responses = set()
        for j in range(i + 1, len(messages)):
            future = messages[j]
            if future.get("role") == "assistant":
                break
            if future.get("role") == "tool":
                tc_id = future.get("tool_call_id")
                if tc_id:
                    tool_ids_with_responses.add(tc_id)

        for tc in tool_calls:
            tc_id = tc.get("id")
            if tc_id in tool_ids_with_responses:
                continue

            repaired_count += 1
            fn = tc.get("function", {})
            tool_name = fn.get("name", "unknown")

            try:
                arguments = json.loads(fn.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                arguments = {}

            result = None
            if work_dir and _is_file_tool(tool_name):
                result = _try_auto_complete_tool(tool_name, arguments, work_dir)

            if result is None:
                result = _build_interrupted_response(tool_name, arguments)

            repaired.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
                "user_output": _build_recovered_user_output(tool_name, arguments),
            })
            log.warning(f"对话修复: 补全丢失的工具调用结果 [{tool_name}] -> {tc_id}")

    if repaired_count > 0:
        log.warning(f"对话修复完成: 共补全 {repaired_count} 个丢失的工具调用结果")

    return repaired


def init_conversation(dir_id, conv_id, conv_name, work_dir):
    """初始化新对话的统一入口。

    - 在 .dpc 索引中注册（若名称已存在则返回现有 conv_id）
    - 创建空的 JSON 会话文件

    返回 (dir_id, conv_id)。
    """
    from modules.chater import dpc_manager

    dir_id = dpc_manager.ensure_dir_id(work_dir)
    conv_id = dpc_manager.add_conversation(work_dir, conv_name)
    save_conversation([], dir_id, conv_id)
    log.info(f"初始化新对话: {conv_name} ({conv_id})")
    return dir_id, conv_id


def save_conversation(messages, dir_id, conv_id):
    """同步将会话保存到文件夹结构（用于同步上下文，如启动阶段）。

    - 会话文件夹：date/conversations/{dir_id}/{conv_id}/
    - 会话文件：{conv_id}/{conv_id}.json
    - 备份管理：{conv_id}/backup_registry.json（由 backup_manager 管理）
    - 备份文件：{conv_id}/backups/{dialog_id}/...
    """
    return _save_conversation_sync(messages, dir_id, conv_id)


def _save_conversation_sync(messages, dir_id, conv_id):
    """底层同步写盘实现。"""
    start = time.perf_counter()
    conv_base_dir = os.path.join(CONVERSATIONS_DIR, dir_id)
    conv_folder = os.path.join(conv_base_dir, conv_id)

    # 创建会话文件夹
    os.makedirs(conv_folder, exist_ok=True)

    # 保存会话文件（先写临时文件再原子替换，避免进程被杀时留下损坏 JSON）
    filepath = os.path.join(conv_folder, f"{conv_id}.json")
    tmp_filepath = f"{filepath}.tmp"
    with open(tmp_filepath, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)
    os.replace(tmp_filepath, filepath)

    elapsed = time.perf_counter() - start
    log.info(f"保存对话: dir={dir_id}, conv={conv_id}, 消息数: {len(messages)}, 耗时={elapsed:.3f}s")


def load_conversation(dir_id, conv_id):
    """从文件夹结构加载会话。

    支持新旧两种格式：
    - 新格式：{dir_id}/{conv_id}/{conv_id}.json
    - 旧格式：{dir_id}/{conv_id}.json（兼容现有数据）
    """
    start = time.perf_counter()
    # 尝试新格式
    new_filepath = os.path.join(CONVERSATIONS_DIR, dir_id, conv_id, f"{conv_id}.json")
    if os.path.exists(new_filepath):
        try:
            with open(new_filepath, 'r', encoding='utf-8') as f:
                messages = json.load(f)
        except json.JSONDecodeError:
            # 进程被强杀可能打断写入，遗留损坏文件：备份后按空对话处理
            backup = f"{new_filepath}.corrupt.{int(time.time())}"
            try:
                os.replace(new_filepath, backup)
            except OSError:
                pass
            log.warning(f"对话文件损坏（已备份为 {backup}），按空对话处理")
            return []
        elapsed = time.perf_counter() - start
        log.info(f"加载对话（新格式）: dir={dir_id}, conv={conv_id}, 消息数: {len(messages)}, 耗时={elapsed:.3f}s")
        return messages
    
    # 尝试旧格式（兼容现有数据）
    old_filepath = os.path.join(CONVERSATIONS_DIR, dir_id, f"{conv_id}.json")
    if os.path.exists(old_filepath):
        try:
            with open(old_filepath, 'r', encoding='utf-8') as f:
                messages = json.load(f)
        except json.JSONDecodeError:
            backup = f"{old_filepath}.corrupt.{int(time.time())}"
            try:
                os.replace(old_filepath, backup)
            except OSError:
                pass
            log.warning(f"对话文件损坏（已备份为 {backup}），按空对话处理")
            return []
        log.info(f"加载对话（旧格式）: dir={dir_id}, conv={conv_id}, 消息数: {len(messages)}")

        # 自动迁移到新格式
        log.info(f"迁移对话到新格式: conv={conv_id}")
        save_conversation(messages, dir_id, conv_id)

        # 删除旧文件
        try:
            os.remove(old_filepath)
            log.info(f"删除旧格式文件: {old_filepath}")
        except Exception as e:
            log.warning(f"删除旧格式文件失败: {e}")

        return messages
    
    log.warning(f"对话不存在: dir={dir_id}, conv={conv_id}")
    return None
