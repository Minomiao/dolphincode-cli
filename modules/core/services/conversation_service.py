"""对话与工作目录服务：从 UI 下沉的纯业务操作。

上下文协议（鸭子类型）：
    ctx.current_config: dict                  当前配置（含 work_directory）
    ctx.chat_instance: DolphinChat            当前对话实例
    ctx.config: 模块                          提供 save_config()
    ctx.conversation_loader: 模块             提供 load_and_activate()
    ctx.current_conversation: str             当前对话名
    ctx.current_dir_id / ctx.current_conv_id: 当前对话标识
"""
import os

from modules import bootstrap
from modules.bootstrap import constants
from modules.logger import get_logger

log = get_logger("Dolphin.conversation_service")


def resolve_work_directory(path):
    """将（可能是相对的）工作目录路径解析为基于项目根的绝对路径。"""
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(bootstrap.PROJECT_ROOT, path))
    return path


def _save_current(ctx):
    """存在有效会话时自动保存当前对话。"""
    if ctx.chat_instance.messages and ctx.current_dir_id and ctx.current_conv_id:
        ctx.chat_instance.save_conversation(ctx.current_dir_id, ctx.current_conv_id)
        log.info(f"自动保存旧对话: {ctx.current_conversation}")


def list_conversations(ctx):
    """获取当前工作目录下的对话列表（.dpc 中的 [{id, name}]）。"""
    from modules.chater import dpc_manager
    work_dir = ctx.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    return dpc_manager.get_conversations(work_dir)


def create_conversation(ctx, new_name):
    """新建对话（同名对话已存在时失败）。

    Returns:
        {success, conv_name, dir_id, conv_id} 或 {success: False, error: 'duplicate'}
    """
    from modules.chater import dpc_manager, conversation

    work_dir = ctx.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    if dpc_manager.get_id_by_name(work_dir, new_name):
        log.warning(f"新建对话被阻止：同名对话已存在 '{new_name}'")
        return {"success": False, "error": "duplicate"}

    _save_current(ctx)

    ctx.chat_instance.clear_history()
    dir_id, conv_id = conversation.init_conversation(None, None, new_name, work_dir)
    ctx.current_conversation = new_name
    ctx.current_dir_id = dir_id
    ctx.current_conv_id = conv_id
    ctx.chat_instance.set_save_target(dir_id, conv_id)
    log.info(f"切换到新对话: {new_name} ({conv_id})")
    return {"success": True, "conv_name": new_name, "dir_id": dir_id, "conv_id": conv_id}


def _activate(ctx, work_dir, conv_id, conv_name):
    """加载并激活指定对话，更新上下文（不含界面刷新）。

    Returns:
        load_and_activate 的结果字典，加载失败返回 None
    """
    from modules.chater import dpc_manager
    dir_id = dpc_manager.ensure_dir_id(work_dir)
    result = ctx.conversation_loader.load_and_activate(
        ctx.chat_instance, dir_id, conv_id, conv_name, work_dir)
    if not result:
        return None
    ctx.current_conversation = result['conv_name']
    ctx.current_dir_id = result['dir_id']
    ctx.current_conv_id = result['conv_id']
    ctx.chat_instance.set_save_target(result['dir_id'], result['conv_id'])
    return result


def activate_conversation(ctx, conv_name):
    """按名称加载已有对话。

    Returns:
        {success, conv_name, dir_id, conv_id} 或
        {success: False, error: 'not_found'/'load_failed'}
    """
    from modules.chater import dpc_manager
    work_dir = ctx.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    conv_id = dpc_manager.get_id_by_name(work_dir, conv_name)
    if not conv_id:
        log.warning(f"对话不存在: {conv_name}")
        return {"success": False, "error": "not_found"}
    result = _activate(ctx, work_dir, conv_id, conv_name)
    if not result:
        return {"success": False, "error": "load_failed"}
    return {"success": True, **result}


def activate_conversation_by_id(ctx, conv_id, conv_name):
    """按 ID 加载对话（供选择界面等已知 ID 的调用方使用）。

    Returns:
        {success, conv_name, dir_id, conv_id} 或 {success: False, error: 'load_failed'}
    """
    work_dir = ctx.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    result = _activate(ctx, work_dir, conv_id, conv_name)
    if not result:
        return {"success": False, "error": "load_failed"}
    return {"success": True, **result}


def open_work_directory(ctx, path, create_if_missing=False):
    """打开/切换工作目录（纯业务，不含界面渲染）。

    流程：解析路径 → 建目录（可选）→ 更新配置 → 重载技能
    → 保存旧对话 → 加载 .dpc 指向的当前对话，无则新建。

    Args:
        ctx: 应用上下文
        path: 目标目录（相对路径基于项目根解析）
        create_if_missing: 目录不存在时是否自动创建

    Returns:
        {success, action, conv_name, skills_reloaded, created_dir, error}
        action: "loaded"（加载已有对话）/ "created"（新建对话）；
        目录不存在且不允许创建时 success 为 False
    """
    from modules.chater import dpc_manager, conversation

    path = resolve_work_directory(path)

    created_dir = False
    if not os.path.exists(path):
        if not create_if_missing:
            return {"success": False, "action": "cancelled", "error": f"目录不存在: {path}"}
        try:
            os.makedirs(path, exist_ok=True)
            created_dir = True
            log.info(f"创建工作目录: {path}")
        except OSError as e:
            log.warning(f"创建工作目录失败: {e}")
            return {"success": False, "action": "create_failed", "error": str(e)}

    old_work_directory = ctx.current_config.get('work_directory', constants.DEFAULT_WORK_DIR)
    skills_reloaded = False
    if path != old_work_directory:
        ctx.current_config['work_directory'] = path
        ctx.config.save_config(ctx.current_config)
        log.info(f"工作目录已更改: {old_work_directory} -> {path}")
        # 复用同一单例重载技能，避免 importlib.reload 造成模块/单例分裂
        sm = ctx.chat_instance.skill_mgr
        sm.reload_skills()
        sm.set_work_dir(path)
        if ctx.chat_instance.plugin_loader:
            ctx.chat_instance.plugin_loader.set_work_dir(path)
        ctx.chat_instance._update_tools()
        skills_reloaded = True

    _save_current(ctx)

    dir_id = dpc_manager.ensure_dir_id(path)
    conv_id, conv_name = dpc_manager.get_current(path)

    if conv_id and conv_name:
        result = ctx.conversation_loader.load_and_activate(
            ctx.chat_instance, dir_id, conv_id, conv_name, path)
        if result:
            ctx.current_conversation = result['conv_name']
            ctx.current_dir_id = result['dir_id']
            ctx.current_conv_id = result['conv_id']
            ctx.chat_instance.set_save_target(result['dir_id'], result['conv_id'])
            return {"success": True, "action": "loaded", "conv_name": result['conv_name'],
                    "skills_reloaded": skills_reloaded, "created_dir": created_dir}

    if conv_id:
        log.warning(".dpc 指向的对话不存在，将创建新对话")

    ctx.chat_instance.clear_history()

    conv_name = os.path.basename(path.rstrip('/\\'))
    if not conv_name:
        conv_name = "default"
    existing_names = [c["name"] for c in dpc_manager.get_conversations(path)]
    base_name = conv_name
    counter = 1
    while conv_name in existing_names:
        conv_name = f"{base_name}_{counter}"
        counter += 1

    dir_id, new_conv_id = conversation.init_conversation(dir_id, None, conv_name, path)
    ctx.current_conversation = conv_name
    ctx.current_dir_id = dir_id
    ctx.current_conv_id = new_conv_id
    ctx.chat_instance.set_save_target(dir_id, new_conv_id)
    log.info(f"为工作目录创建新对话: {conv_name} ({new_conv_id})")
    return {"success": True, "action": "created", "conv_name": conv_name,
            "skills_reloaded": skills_reloaded, "created_dir": created_dir}
