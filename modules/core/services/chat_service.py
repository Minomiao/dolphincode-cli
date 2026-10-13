"""对话实例服务：DolphinChat 实例的构建与重建。

上下文协议（鸭子类型）：
    ctx.chat_instance: DolphinChat 或 None   当前对话实例
    ctx.chat: 模块                            提供 DolphinChat 类
    ctx.current_config: dict                  当前配置（model / max_tokens）
    ctx.effort_level: str                     思考深度
    ctx.current_dir_id / ctx.current_conv_id: 当前对话标识
"""
from modules.bootstrap import constants
from modules.logger import get_logger

log = get_logger("Dolphin.chat_service")


def rebuild_chat_instance(ctx, callback=None):
    """根据当前配置重建对话实例（保留消息、思考深度与保存目标）。

    Args:
        ctx: 应用上下文
        callback: 新实例的事件回调；未提供时沿用旧实例的回调

    Returns:
        {success: True, instance: 新实例}
    """
    # 保留旧实例的消息，避免对话历史丢失
    old_messages = []
    if ctx.chat_instance is not None:
        old_messages = ctx.chat_instance.messages
        if callback is None:
            callback = getattr(ctx.chat_instance, 'callback', None)

    ctx.chat_instance = ctx.chat.DolphinChat(
        model=ctx.current_config.get('model'),
        max_tokens=ctx.current_config.get('max_tokens', constants.DEFAULT_MAX_TOKENS),
        callback=callback
    )
    ctx.chat_instance.messages = old_messages
    ctx.chat_instance.effort_level = ctx.effort_level
    # 恢复保存目标，避免重建后自动保存失效导致退出丢失本轮消息
    if ctx.current_dir_id and ctx.current_conv_id:
        ctx.chat_instance.set_save_target(ctx.current_dir_id, ctx.current_conv_id)
    log.info("客户端已更新")
    return {"success": True, "instance": ctx.chat_instance}
