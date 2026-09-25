import os
import re
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv, set_key, unset_key
from modules.logger import get_logger
from modules import bootstrap as app_paths

from modules.bootstrap import constants

log = get_logger("Dolphin.config")


def init():
    """显式初始化配置模块：加载 .env、补全 .env 文件、迁移并补全配置键。

    由 main.py 在启动时调用一次，避免模块导入时产生副作用。
    """
    load_dotenv(app_paths.ENV_FILE)
    _ensure_env_file()
    _migrate_models_file()
    ensure_config()


def _ensure_env_file():
    """如果 .env 不存在且 config.json 存在，自动导入 api_key 和 work_directory 到 .env"""
    env_path = Path(app_paths.ENV_FILE)
    if env_path.exists():
        return

    api_key = ""
    work_dir = ""
    if os.path.exists(app_paths.CONFIG_FILE):
        try:
            with open(app_paths.CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            api_key = config_data.get("api_key", "")
            work_dir = config_data.get("work_directory", "")
        except FileNotFoundError:
            log.warning("config.json 文件不存在")
        except PermissionError as e:
            log.warning(f"无权限读取 config.json: {e}")
        except json.JSONDecodeError as e:
            log.warning(f"config.json 格式错误: {e}")
        except Exception as e:
            log.warning(f"读取 config.json 发生意外错误: {e}")

    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.touch()
        if api_key:
            set_key(app_paths.ENV_FILE, "QUICKAI_API_KEY", api_key)
        if work_dir:
            set_key(app_paths.ENV_FILE, "QUICKAI_WORK_DIRECTORY", work_dir)
        log.info(f"已自动创建 .env 文件并从 config.json 导入配置")
        load_dotenv(app_paths.ENV_FILE, override=True)
    except PermissionError as e:
        log.warning(f"无权限创建 .env 文件: {e}")
    except OSError as e:
        log.warning(f"创建 .env 文件失败 (操作系统错误): {e}")
    except Exception as e:
        log.warning(f"创建 .env 文件发生意外错误: {e}")

# 模型元数据缺失时的兜底上下文窗口
DEFAULT_CONTEXT_WINDOW = 128000

# models.json 缓存：(文件路径, 数据)，路径变化时自动失效
_models_cache = None


def _seed_models():
    """内置模型的种子定义，允许用 QUICKAI_BASE_URL 覆盖内置服务地址。"""
    env_base_url = os.getenv("QUICKAI_BASE_URL")
    seeds = []
    for seed in constants.DEFAULT_MODELS:
        entry = dict(seed)
        if env_base_url:
            entry["base_url"] = env_base_url
        seeds.append(entry)
    return seeds


def _derive_api_key_env(model_name):
    """由模型名派生 .env 中的密钥变量名（非法字符替换为下划线）。"""
    sanitized = re.sub(r"[^0-9A-Za-z]+", "_", model_name).strip("_").upper()
    if not sanitized:
        return "QUICKAI_API_KEY_CUSTOM"
    return f"QUICKAI_API_KEY_{sanitized}"


def _next_free_env_name(base_name, used_names):
    """在已占用的变量名之外取一个可用的变量名（追加序号）。"""
    index = 2
    candidate = f"{base_name}_{index}"
    while candidate in used_names:
        index += 1
        candidate = f"{base_name}_{index}"
    return candidate


def _allocate_env_name(base_name, used_names):
    """取一个未被占用的密钥变量名：base 空闲则用 base，否则追加序号。

    默认变量（内置模型共用）不允许被自定义模型占用。
    """
    if base_name == constants.DEFAULT_API_KEY_ENV or base_name in used_names:
        return _next_free_env_name(base_name, used_names)
    return base_name


def _ensure_env_file_exists():
    """确保 .env 文件存在，返回是否可用。"""
    try:
        env_path = Path(app_paths.ENV_FILE)
        if not env_path.exists():
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch()
        return True
    except (PermissionError, OSError) as e:
        log.warning(f"创建 .env 文件失败: {e}")
        return False


def _write_env_key(env_name, value):
    """把密钥写入 .env 的指定变量（变量不存在则追加）。

    Returns:
        True 成功 / False 失败
    """
    if not env_name or not _ensure_env_file_exists():
        return False
    try:
        # 值为空时也写入，避免 .env 残留旧密钥
        set_key(app_paths.ENV_FILE, env_name, value)
        load_dotenv(app_paths.ENV_FILE, override=True)
        return True
    except PermissionError as e:
        log.warning(f"无权限更新 .env 文件: {e}")
    except OSError as e:
        log.warning(f"更新 .env 文件失败 (操作系统错误): {e}")
    except Exception as e:
        log.warning(f"更新 .env 文件发生意外错误: {e}")
    return False


def _remove_env_key(env_name):
    """删除 .env 中指定变量（不存在时静默返回）。"""
    if not env_name or not os.path.exists(app_paths.ENV_FILE):
        return
    try:
        unset_key(app_paths.ENV_FILE, env_name)
        load_dotenv(app_paths.ENV_FILE, override=True)
    except PermissionError as e:
        log.warning(f"无权限更新 .env 文件: {e}")
    except OSError as e:
        log.warning(f"更新 .env 文件失败 (操作系统错误): {e}")
    except Exception as e:
        log.warning(f"更新 .env 文件发生意外错误: {e}")


def _write_env_work_dir(work_dir):
    """把工作目录写入 .env（为空时跳过）。"""
    if work_dir:
        _write_env_key("QUICKAI_WORK_DIRECTORY", work_dir)


def _normalize_models(file_data):
    """把 models.json 内容规整为统一清单 {current, models}。

    - 已是统一清单：保留原有条目与顺序，仅补入缺失的内置模型
    - 旧结构 {current, base_url, custom_models}：内置种子套用顶层 base_url 后与自定义模型合并
    - 条目已存在时一律以文件为准，不被种子覆盖
    - 补齐 api_key_env：非自定义条目指向默认变量，自定义条目按模型名派生且互不重复
    """
    if isinstance(file_data.get("models"), list):
        models = [dict(m) for m in file_data["models"]
                  if isinstance(m, dict) and m.get("name")]
    else:
        legacy_base_url = file_data.get("base_url")
        models = []
        for seed in _seed_models():
            entry = dict(seed)
            if legacy_base_url:
                entry["base_url"] = legacy_base_url
            models.append(entry)
        legacy_custom = file_data.get("custom_models")
        if isinstance(legacy_custom, list):
            models.extend(dict(m) for m in legacy_custom
                          if isinstance(m, dict) and m.get("name"))

    existing = {m.get("name") for m in models}
    models.extend(dict(seed) for seed in _seed_models() if seed["name"] not in existing)

    used_env_names = set()
    for entry in models:
        if entry.get("custom"):
            env_name = entry.get("api_key_env")
            if not env_name or env_name == constants.DEFAULT_API_KEY_ENV:
                env_name = _allocate_env_name(_derive_api_key_env(entry["name"]), used_env_names)
            elif env_name in used_env_names:
                log.warning(f"模型 '{entry['name']}' 的密钥变量 {env_name} 与其他模型重复，已重新分配")
                env_name = _allocate_env_name(_derive_api_key_env(entry["name"]), used_env_names)
        else:
            env_name = entry.get("api_key_env") or constants.DEFAULT_API_KEY_ENV
        entry["api_key_env"] = env_name
        used_env_names.add(env_name)

    return {
        "current": file_data.get("current") or constants.DEFAULT_MODEL,
        "models": models,
    }


def _migrate_models_file():
    """创建或升级 models.json，使其成为模型配置的唯一清单。

    处理四种情况：
    - 文件不存在：以内置种子 + 旧版分散数据（config.json 的 model/base_url、
      custom_models.json）生成
    - 文件为旧结构（{current, base_url, custom_models}）：转换为统一 models 列表
    - 文件缺少新增的内置模型：补入（已存在的条目不覆盖）
    - 条目里残留 api_key：搬进 .env 对应变量，改为 api_key_env 映射
    """
    file_exists = os.path.exists(app_paths.MODELS_FILE)
    file_data = _read_json(app_paths.MODELS_FILE, "models.json") if file_exists else {}
    if not isinstance(file_data, dict):
        file_data = {}

    if not file_exists:
        legacy_config = _read_json(app_paths.CONFIG_FILE, "config.json")
        if legacy_config.get("model"):
            file_data["current"] = legacy_config["model"]
        if legacy_config.get("base_url"):
            file_data["base_url"] = legacy_config["base_url"]

        legacy_custom_file = os.path.join(app_paths.DATE_DIR, "custom_models.json")
        if os.path.exists(legacy_custom_file):
            legacy_custom = _read_json(legacy_custom_file, "custom_models.json")
            if isinstance(legacy_custom, list):
                file_data["custom_models"] = legacy_custom

    normalized = _normalize_models(file_data)

    # 密钥迁移：只有成功写入 .env 后才从条目中移除，避免密钥丢失
    moved_keys = 0
    for entry in normalized["models"]:
        legacy_key = entry.get("api_key")
        if legacy_key is None:
            continue
        if _write_env_key(entry["api_key_env"], legacy_key):
            entry.pop("api_key", None)
            moved_keys += 1

    if normalized == file_data:
        return

    if _save_models(normalized):
        log.info(f"已写入 models.json（模型 {len(normalized['models'])} 个，当前 {normalized['current']}）")
        if moved_keys:
            log.info(f"已将 {moved_keys} 个模型的密钥迁移到 .env")


def _load_models():
    """读取 models.json（带缓存），缺失或损坏时回退到内置种子。"""
    global _models_cache
    path = app_paths.MODELS_FILE
    if _models_cache is not None and _models_cache[0] == path:
        return _models_cache[1]

    file_data = _read_json(path, "models.json") if os.path.exists(path) else {}
    if not isinstance(file_data, dict):
        log.warning("models.json 结构异常，已回退到内置模型种子")
        file_data = {}

    data = _normalize_models(file_data)
    _models_cache = (path, data)
    return data


def _save_models(models):
    """保存 models.json 并刷新缓存。

    Returns:
        True 成功 / False 失败
    """
    global _models_cache
    path = app_paths.MODELS_FILE
    if not _write_json_atomic(path, models):
        return False
    _models_cache = (path, models)
    return True


def _allocated_env_names():
    """收集已被模型占用的 .env 变量名。"""
    names = set()
    for m in _load_models().get("models", []):
        env_name = m.get("api_key_env")
        if env_name:
            names.add(env_name)
    return names


def add_custom_model(name, description, base_url, api_key,
                     context_window=DEFAULT_CONTEXT_WINDOW, vision=False):
    """添加一个自定义模型，密钥写入 .env 并记录映射变量名。

    Args:
        name: 模型名称（唯一标识）
        description: 模型描述
        base_url: API 地址
        api_key: API 密钥（存入 .env，不写入 models.json）
        context_window: 上下文窗口大小
        vision: 是否为多模态（支持图片输入）模型

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    if get_model_metadata(name):
        return False, f"模型名 '{name}' 已存在"

    env_name = _allocate_env_name(_derive_api_key_env(name), _allocated_env_names())
    if not _write_env_key(env_name, api_key):
        return False, "写入 .env 失败"

    capabilities = [constants.MODEL_CAPABILITY_VISION] if vision else []
    models = dict(_load_models())
    models["models"] = list(models.get("models", [])) + [{
        "name": name,
        "description": description,
        "base_url": base_url,
        "context_window": context_window,
        "api_key_env": env_name,
        "capabilities": capabilities,
        "custom": True,
    }]
    if not _save_models(models):
        return False, "保存模型配置失败"
    log.info(f"已添加自定义模型: {name}（密钥变量 {env_name}，多模态={vision}）")
    return True, ""


def remove_custom_model(name):
    """删除一个自定义模型（内置模型不可删除），并清理其在 .env 中的密钥。

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    models = _load_models()
    entries = list(models.get("models", []))
    for i, m in enumerate(entries):
        if m.get("name") != name:
            continue
        if not m.get("custom"):
            return False, f"内置模型 '{name}' 不可删除"
        updated = dict(models)
        updated["models"] = entries[:i] + entries[i + 1:]
        if not _save_models(updated):
            return False, "保存模型配置失败"
        # 条目删除成功后再清理 .env，共享的默认变量不动
        env_name = m.get("api_key_env")
        if env_name and env_name != constants.DEFAULT_API_KEY_ENV:
            _remove_env_key(env_name)
        log.info(f"已删除自定义模型: {name}")
        return True, ""
    return False, f"未找到自定义模型 '{name}'"


def get_model_metadata(model_name):
    """获取模型元数据（来自 models.json 的统一清单），未找到返回 None。"""
    for m in _load_models().get("models", []):
        if m.get("name") == model_name:
            return m
    return None


def set_model_api_key(model_name, api_key):
    """更新指定模型映射的 .env 密钥（不改变当前模型）。

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    meta = get_model_metadata(model_name)
    if not meta:
        return False, f"未找到模型 '{model_name}'"
    env_name = meta.get("api_key_env") or constants.DEFAULT_API_KEY_ENV
    if not _write_env_key(env_name, api_key):
        return False, "写入 .env 失败"
    log.info(f"模型 '{model_name}' 的密钥已更新（变量 {env_name}）")
    return True, ""


def update_custom_model(model_name, description=None, base_url=None,
                        context_window=None, api_key=None, vision=None):
    """更新自定义模型的配置（模型名不可修改）。

    api_key 写入该模型映射的 .env 变量，其余字段写入 models.json；
    参数为 None 表示保持不变。

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    models = _load_models()
    entries = list(models.get("models", []))
    for i, m in enumerate(entries):
        if m.get("name") != model_name:
            continue
        if not m.get("custom"):
            return False, f"内置模型 '{model_name}' 不可修改配置"

        updated = dict(models)
        updated["models"] = [dict(e) for e in entries]
        target = updated["models"][i]
        if description is not None:
            target["description"] = description
        if base_url is not None:
            target["base_url"] = base_url
        if context_window is not None:
            target["context_window"] = context_window
        if vision is not None:
            caps = [c for c in target.get("capabilities", [])
                    if c != constants.MODEL_CAPABILITY_VISION]
            if vision:
                caps.append(constants.MODEL_CAPABILITY_VISION)
            target["capabilities"] = caps

        if api_key is not None:
            env_name = target.get("api_key_env") or constants.DEFAULT_API_KEY_ENV
            if not _write_env_key(env_name, api_key):
                return False, "写入 .env 失败"

        if not _save_models(updated):
            return False, "保存模型配置失败"
        log.info(f"已更新模型配置: {model_name}")
        return True, ""
    return False, f"未找到模型 '{model_name}'"


def resolve_model_credentials(model_name):
    """解析指定模型生效的 base_url 与 api_key。

    服务地址随模型条目存放；密钥统一存放在 .env，
    条目通过 api_key_env 指向变量名（默认模型共用 DEFAULT_API_KEY_ENV）。
    """
    meta = get_model_metadata(model_name) or {}
    env_name = meta.get("api_key_env") or constants.DEFAULT_API_KEY_ENV
    return {
        "base_url": meta.get("base_url") or constants.DEFAULT_BASE_URL,
        "api_key": os.getenv(env_name, ""),
    }


def get_available_models():
    """获取可用模型列表（顺序即 models.json 中的顺序）。"""
    return list(_load_models().get("models", []))

def get_context_window(model_name: str) -> int:
    """获取指定模型的上下文窗口大小，未记录时回退 128000。"""
    model_info = get_model_metadata(model_name) or {}
    return model_info.get("context_window", DEFAULT_CONTEXT_WINDOW)

def check_model_deprecation(model_name):
    """检查模型是否已废弃或即将废弃，返回警告信息"""
    model_info = get_model_metadata(model_name) or {}
    if not model_info.get("deprecated"):
        return None

    deprecation_date_str = model_info.get("deprecation_date", "")
    replacement = model_info.get("replacement", "")

    try:
        deprecation_date = datetime.strptime(deprecation_date_str, "%Y-%m-%d")
        now = datetime.now()

        if now >= deprecation_date:
            msg = f"模型 '{model_name}' 已于 {deprecation_date_str} 废弃"
        else:
            days_left = (deprecation_date - now).days
            msg = f"模型 '{model_name}' 将于 {deprecation_date_str} 废弃 (剩余 {days_left} 天)"

        if replacement:
            msg += f"，请改用 '{replacement}'"
        return msg
    except (ValueError, TypeError):
        return None

def _get_default_config():
    """config.json 的默认结构（模型字段见 models.json，敏感字段见 .env）。"""
    return {
        "language": "zh-CN",
        "command_prefix": "/",
        "max_tokens": 18000,
        "reasoning": True,
        "skills": {"web_search": True},
        "plugins": {},
        "show_thinking": False,
    }


def load_config():
    """加载完整配置：config.json + models.json + .env，返回扁平字典。

    返回的 dict 始终包含 model / base_url / api_key / work_directory，
    其值为当前模型解析后的实际生效值。
    """
    defaults = _get_default_config()
    file_data = _read_json(app_paths.CONFIG_FILE, "config.json")

    config_data = dict(defaults)
    config_data.update({k: v for k, v in file_data.items()
                        if k not in ("api_key", "work_directory", "model", "base_url")})

    model_name = _load_models().get("current", constants.DEFAULT_MODEL)
    config_data["model"] = model_name
    config_data.update(resolve_model_credentials(model_name))
    config_data["work_directory"] = os.getenv("QUICKAI_WORK_DIRECTORY", "workplace")
    return config_data


def save_config(config):
    """保存配置：模型选择 → models.json，密钥/工作目录 → .env，其余 → config.json。

    密钥写入当前模型映射的 .env 变量（见条目的 api_key_env），
    models.json 中不保留任何密钥明文。
    """
    model_name = config.get("model", constants.DEFAULT_MODEL)

    models = dict(_load_models())
    models["models"] = [dict(m) for m in models.get("models", [])]
    models["current"] = model_name

    meta = next((m for m in models["models"] if m.get("name") == model_name), {})
    _write_env_key(meta.get("api_key_env") or constants.DEFAULT_API_KEY_ENV,
                   config.get("api_key", ""))
    _write_env_work_dir(config.get("work_directory", ""))

    _save_models(models)

    config_to_save = {k: v for k, v in config.items()
                      if k not in ("api_key", "work_directory", "model", "base_url")}
    _write_json_atomic(app_paths.CONFIG_FILE, config_to_save)


def _read_json(path, label):
    """读取 JSON 文件，不存在或解析失败时返回空字典。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        log.debug(f"加载{label}: {path}")
        return data
    except FileNotFoundError:
        log.warning(f"{label} 不存在: {path}")
    except PermissionError as e:
        log.error(f"无权限读取{label}: {e}")
    except json.JSONDecodeError as e:
        log.error(f"{label} JSON 格式错误: {e}")
    except Exception as e:
        log.error(f"读取{label}发生意外错误: {e}")
    return {}


def _write_json_atomic(path, data):
    """原子写入 JSON 文件：先写临时文件再替换，避免写一半中断损坏文件。

    Returns:
        True 成功 / False 失败
    """
    directory = os.path.dirname(path)
    try:
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
    except OSError as e:
        log.warning(f"创建目录失败 {directory}: {e}")
        return False

    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except PermissionError as e:
        log.warning(f"无权限写入 {os.path.basename(path)}: {e}")
    except OSError as e:
        log.warning(f"写入 {os.path.basename(path)} 失败 (操作系统错误): {e}")
        _remove_tmp_config(tmp_path)
    except (TypeError, ValueError) as e:
        log.warning(f"{os.path.basename(path)} 序列化失败: {e}")
        _remove_tmp_config(tmp_path)
    except Exception as e:
        log.warning(f"写入 {os.path.basename(path)} 发生意外错误: {e}")
        _remove_tmp_config(tmp_path)
    else:
        log.debug(f"保存文件: {path}")
        return True
    return False


def _remove_tmp_config(tmp_path):
    """清理原子写入失败时遗留的临时文件。"""
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass


def ensure_config():
    """确保 config.json 包含所有默认键，并清理已迁移的旧字段（仅启动时调用一次）。"""
    if not os.path.exists(app_paths.CONFIG_FILE):
        return

    defaults = _get_default_config()
    file_data = _read_json(app_paths.CONFIG_FILE, "config.json")

    legacy_keys = [k for k in ("model", "base_url", "api_key", "work_directory") if k in file_data]
    missing_keys = [k for k in defaults if k not in file_data]
    if not legacy_keys and not missing_keys:
        return

    if legacy_keys:
        log.info(f"清理 config.json 中已迁移的字段: {legacy_keys}")
    if missing_keys:
        log.info(f"补全缺失的配置键: {missing_keys}")

    config_data = dict(defaults)
    config_data.update({k: v for k, v in file_data.items()
                        if k not in ("api_key", "work_directory", "model", "base_url")})
    _write_json_atomic(app_paths.CONFIG_FILE, config_data)
