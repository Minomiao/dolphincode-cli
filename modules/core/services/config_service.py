"""配置服务：模型、参数与显示偏好等配置项的纯业务读写。

上下文协议（鸭子类型）：
    ctx.current_config: dict                  当前配置
    ctx.chat_instance: DolphinChat            当前对话实例
    ctx.chat: 模块                            提供 DolphinChat 类（用于重建）
    ctx.config: 模块                          提供 save_config() / remove_custom_model() / update_custom_model() / set_model_api_key()
    ctx.cmd: 模块                             提供 save_commands()（前缀变更时）
    ctx.show_thinking: bool                   思考过程显示开关
    ctx.effort_level: str                     思考深度
"""
from modules.bootstrap import constants
from modules.logger import get_logger
from . import chat_service

log = get_logger("Dolphin.config_service")

# 最大 Token 数上下限（上限对齐 DeepSeek 官方文档的 384K 输出长度）
MIN_MAX_TOKENS = 1
MAX_MAX_TOKENS = 393216
# 命令前缀最大长度（超出截断）
COMMAND_PREFIX_MAX_LEN = 10
# 合法的思考深度
VALID_EFFORT_LEVELS = ('fine', 'normal', 'high')


def get_settings(ctx):
    """读取当前可配置项快照。"""
    return {
        "model": ctx.current_config.get('model', constants.DEFAULT_MODEL),
        "max_tokens": ctx.current_config.get('max_tokens', 18000),
        "command_prefix": ctx.current_config.get('command_prefix', '/'),
        "show_thinking": ctx.show_thinking,
        "effort_level": ctx.effort_level,
    }


def set_max_tokens(ctx, value):
    """设置最大 Token 数。

    Args:
        ctx: 应用上下文
        value: 新的最大 Token 数（int）

    Returns:
        {success, value} 或 {success: False, error: 'min'/'max'}
    """
    if value < MIN_MAX_TOKENS:
        return {"success": False, "error": "min"}
    if value > MAX_MAX_TOKENS:
        return {"success": False, "error": "max"}
    ctx.current_config['max_tokens'] = value
    ctx.config.save_config(ctx.current_config)
    log.info(f"最大 Token 数已更改: {value}")
    return {"success": True, "value": value}


def set_command_prefix(ctx, prefix):
    """设置命令前缀（超长自动截断）并同步命令文件。

    Returns:
        {success, value, truncated}
    """
    truncated = len(prefix) > COMMAND_PREFIX_MAX_LEN
    if truncated:
        prefix = prefix[:COMMAND_PREFIX_MAX_LEN]
    ctx.current_config['command_prefix'] = prefix
    ctx.config.save_config(ctx.current_config)
    ctx.cmd.save_commands()
    log.info(f"命令前缀已更改: {prefix}")
    return {"success": True, "value": prefix, "truncated": truncated}


def set_show_thinking(ctx, enabled):
    """设置思考过程显示开关。

    Returns:
        {success, changed, enabled}：changed 表示是否发生实际变更
    """
    if ctx.show_thinking == enabled:
        return {"success": True, "changed": False, "enabled": enabled}
    ctx.show_thinking = enabled
    ctx.current_config['show_thinking'] = enabled
    ctx.config.save_config(ctx.current_config)
    return {"success": True, "changed": True, "enabled": enabled}


def set_effort_level(ctx, level):
    """设置思考深度并同步到对话实例。

    Returns:
        {success, value} 或 {success: False, error: 'invalid'}
    """
    if level not in VALID_EFFORT_LEVELS:
        return {"success": False, "error": "invalid"}
    ctx.effort_level = level
    if ctx.chat_instance is not None:
        ctx.chat_instance.effort_level = level
    ctx.current_config['effort_level'] = level
    ctx.config.save_config(ctx.current_config)
    log.info(f"思考深度已更改: {level}")
    return {"success": True, "value": level}


def switch_model(ctx, model_info):
    """切换模型并按模型解析凭据，然后重建客户端。

    Args:
        ctx: 应用上下文
        model_info: 模型信息字典（get_available_models() 的元素）

    Returns:
        {success, value, rebuilt}
    """
    new_model = model_info["name"]
    ctx.current_config['model'] = new_model
    # 凭据按模型解析：自定义模型用自身配置，内置模型回退到默认服务地址与 .env 密钥
    ctx.current_config.update(ctx.config.resolve_model_credentials(new_model))
    ctx.config.save_config(ctx.current_config)
    log.info(f"模型已切换: {new_model}")
    rebuild = chat_service.rebuild_chat_instance(ctx)
    return {"success": True, "value": new_model, "rebuilt": rebuild.get('success')}


def set_api_key(ctx, api_key):
    """更新 API 密钥并重建客户端。

    Returns:
        {success, rebuilt}
    """
    ctx.current_config['api_key'] = api_key
    ctx.config.save_config(ctx.current_config)
    log.info("API 密钥已更新")
    rebuild = chat_service.rebuild_chat_instance(ctx)
    return {"success": True, "rebuilt": rebuild.get('success')}


def set_model_api_key(ctx, model_name, api_key):
    """更新指定模型的 API 密钥。

    若该模型正是当前模型，会同步内存配置并重建客户端；
    否则只更新它在 .env 中映射的变量，不触碰当前模型。

    Returns:
        {success, rebuilt} 或 {success: False, error}
    """
    if ctx.current_config.get('model') == model_name:
        return set_api_key(ctx, api_key)
    success, error = ctx.config.set_model_api_key(model_name, api_key)
    return {"success": success, "error": error}


def update_model(ctx, model_name, values):
    """更新指定模型的配置；若它正是当前模型则同步内存并重建客户端。

    Args:
        model_name: 目标模型名
        values: {字段名: 新值}，可含 description / base_url / context_window /
            api_key / vision；仅传 api_key 时走按模型写密钥的分支

    Returns:
        {success, rebuilt} 或 {success: False, error}
    """
    if set(values) == {"api_key"}:
        return set_model_api_key(ctx, model_name, values["api_key"])

    success, error = ctx.config.update_custom_model(
        model_name,
        description=values.get("description"),
        base_url=values.get("base_url"),
        context_window=values.get("context_window"),
        api_key=values.get("api_key"),
        vision=values.get("vision"))
    if not success:
        return {"success": False, "error": error}

    is_current = ctx.current_config.get('model') == model_name
    if is_current:
        # 服务地址等凭据可能已变化，刷新内存配置并重建客户端
        ctx.current_config.update(ctx.config.resolve_model_credentials(model_name))
        chat_service.rebuild_chat_instance(ctx)
    log.info(f"模型配置已更新: {model_name}")
    return {"success": True, "rebuilt": is_current}


def remove_custom_model(ctx, name):
    """删除自定义模型；若当前正在使用则切回默认模型并同步客户端。

    Returns:
        {success, error}：error 为失败原因（成功时为 None）
    """
    was_current = ctx.current_config.get('model') == name
    success, error = ctx.config.remove_custom_model(name)
    if success and was_current:
        ctx.current_config['model'] = constants.DEFAULT_MODEL
        ctx.current_config.update(ctx.config.resolve_model_credentials(constants.DEFAULT_MODEL))
        ctx.config.save_config(ctx.current_config)
        chat_service.rebuild_chat_instance(ctx)
    return {"success": success, "error": error}
