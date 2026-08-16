import os
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv, set_key
from modules.logger import get_logger
from modules import bootstrap as app_paths

from modules.bootstrap import constants

log = get_logger("Dolphin.config")


def init():
    """显式初始化配置模块：加载 .env、补全 .env 文件、补全配置键。

    由 main.py 在启动时调用一次，避免模块导入时产生副作用。
    """
    load_dotenv(app_paths.ENV_FILE)
    _ensure_env_file()
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

MODEL_REGISTRY = constants.MODEL_REGISTRY

# 自定义模型缓存
_custom_models_cache = None


def _load_custom_models():
    """从 custom_models.json 加载用户自定义模型列表。"""
    global _custom_models_cache
    if _custom_models_cache is not None:
        return _custom_models_cache

    if not os.path.exists(app_paths.CUSTOM_MODELS_FILE):
        _custom_models_cache = []
        return _custom_models_cache

    try:
        with open(app_paths.CUSTOM_MODELS_FILE, 'r', encoding='utf-8') as f:
            _custom_models_cache = json.load(f)
    except FileNotFoundError:
        _custom_models_cache = []
    except (PermissionError, json.JSONDecodeError) as e:
        log.warning(f"读取自定义模型文件失败: {e}")
        _custom_models_cache = []
    except Exception as e:
        log.warning(f"读取自定义模型文件发生意外错误: {e}")
        _custom_models_cache = []

    return _custom_models_cache


def _save_custom_models(models):
    """保存用户自定义模型列表到 custom_models.json。"""
    global _custom_models_cache
    try:
        if not os.path.exists(app_paths.DATE_DIR):
            os.makedirs(app_paths.DATE_DIR)
        with open(app_paths.CUSTOM_MODELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(models, f, ensure_ascii=False, indent=2)
        _custom_models_cache = models
        log.info(f"已保存 {len(models)} 个自定义模型")
    except (PermissionError, OSError) as e:
        log.warning(f"保存自定义模型文件失败: {e}")
    except Exception as e:
        log.warning(f"保存自定义模型文件发生意外错误: {e}")


def add_custom_model(name, description, base_url, api_key, context_window=128000):
    """添加一个自定义模型。

    Args:
        name: 模型名称（唯一标识）
        description: 模型描述
        base_url: API 地址
        api_key: API 密钥
        context_window: 上下文窗口大小

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    # 检查是否与内置模型重名
    if name in MODEL_REGISTRY:
        return False, f"模型名 '{name}' 与内置模型冲突"

    custom_models = _load_custom_models()
    for m in custom_models:
        if m.get("name") == name:
            return False, f"模型名 '{name}' 已存在"

    new_model = {
        "name": name,
        "description": description,
        "base_url": base_url,
        "api_key": api_key,
        "context_window": context_window,
        "custom": True,
    }
    custom_models.append(new_model)
    _save_custom_models(custom_models)
    return True, ""


def remove_custom_model(name):
    """删除一个自定义模型。

    Returns:
        (True, "") 成功 / (False, 错误信息) 失败
    """
    custom_models = _load_custom_models()
    for i, m in enumerate(custom_models):
        if m.get("name") == name:
            custom_models.pop(i)
            _save_custom_models(custom_models)
            return True, ""
    return False, f"未找到自定义模型 '{name}'"


def get_custom_model(name):
    """根据名称查找自定义模型，返回模型信息或 None。"""
    custom_models = _load_custom_models()
    for m in custom_models:
        if m.get("name") == name:
            return m
    return None


def get_available_models():
    """获取可用模型列表（内置 + 自定义），返回带有模型信息的列表"""
    models = []
    for model_name, model_info in MODEL_REGISTRY.items():
        models.append(model_info)
    custom_models = _load_custom_models()
    for m in custom_models:
        models.append(m)
    return models

def get_context_window(model_name: str) -> int:
    """获取指定模型的上下文窗口大小。"""
    model_info = MODEL_REGISTRY.get(model_name, {})
    return model_info.get("context_window", 128000)

def check_model_deprecation(model_name):
    """检查模型是否已废弃或即将废弃，返回警告信息"""
    if model_name not in MODEL_REGISTRY:
        return None
    
    model_info = MODEL_REGISTRY[model_name]
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
    return {
        "base_url": os.getenv("QUICKAI_BASE_URL", "https://api.deepseek.com"),
        "model": "deepseek-v4-flash",
        "language": "zh-CN",
        "command_prefix": "/",
        "max_tokens": 18000,
        "reasoning": True,
        "skills": {"web_search": True},
        "plugins": {},
        "show_thinking": False,
    }


def load_config():
    defaults = _get_default_config()

    if os.path.exists(app_paths.CONFIG_FILE):
        try:
            with open(app_paths.CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
                log.debug(f"加载配置文件: {app_paths.CONFIG_FILE}")
        except FileNotFoundError:
            log.warning(f"配置文件不存在: {app_paths.CONFIG_FILE}")
            file_data = {}
        except PermissionError as e:
            log.error(f"无权限读取配置文件: {e}")
            file_data = {}
        except json.JSONDecodeError as e:
            log.error(f"配置文件 JSON 格式错误: {e}")
            file_data = {}
        except Exception as e:
            log.error(f"加载配置文件发生意外错误: {e}")
            file_data = {}
    else:
        file_data = {}

    config_data = dict(defaults)
    config_data.update({k: v for k, v in file_data.items() if k not in ("api_key", "work_directory")})
    # api_key 和 work_directory 以 .env 环境变量为准，config.json 中不再存储
    config_data["api_key"] = os.getenv("QUICKAI_API_KEY", "")
    config_data["work_directory"] = os.getenv("QUICKAI_WORK_DIRECTORY", "workplace")

    return config_data


def save_config(config):
    try:
        api_key = config.get("api_key", "")
        work_dir = config.get("work_directory", "")
        env_path = Path(app_paths.ENV_FILE)
        if not env_path.exists():
            env_path.parent.mkdir(parents=True, exist_ok=True)
            env_path.touch()
        if api_key:
            set_key(app_paths.ENV_FILE, "QUICKAI_API_KEY", api_key)
        if work_dir:
            set_key(app_paths.ENV_FILE, "QUICKAI_WORK_DIRECTORY", work_dir)
        load_dotenv(app_paths.ENV_FILE, override=True)
    except PermissionError as e:
        log.warning(f"无权限更新 .env 文件: {e}")
    except OSError as e:
        log.warning(f"更新 .env 文件失败 (操作系统错误): {e}")
    except Exception as e:
        log.warning(f"更新 .env 文件发生意外错误: {e}")

    config_to_save = {k: v for k, v in config.items() if k not in ("api_key", "work_directory")}
    if not os.path.exists(app_paths.DATE_DIR):
        try:
            os.makedirs(app_paths.DATE_DIR)
        except OSError as e:
            log.warning(f"创建 date 目录失败: {e}")
            return
    tmp_path = app_paths.CONFIG_FILE + ".tmp"
    try:
        # 原子写：先写临时文件再替换，避免写一半中断损坏 config.json
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(config_to_save, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, app_paths.CONFIG_FILE)
    except PermissionError as e:
        log.warning(f"无权限保存配置文件: {e}")
    except OSError as e:
        log.warning(f"保存配置文件失败 (操作系统错误): {e}")
        _remove_tmp_config(tmp_path)
    except Exception as e:
        log.warning(f"保存配置文件发生意外错误: {e}")
        _remove_tmp_config(tmp_path)
    else:
        log.debug(f"保存配置文件: {app_paths.CONFIG_FILE}")


def _remove_tmp_config(tmp_path):
    """清理原子写入失败时遗留的临时文件。"""
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass


def ensure_config():
    """确保配置文件包含所有默认键，补全新增配置项（仅在启动时调用一次）。"""
    defaults = _get_default_config()
    if not os.path.exists(app_paths.CONFIG_FILE):
        return

    try:
        with open(app_paths.CONFIG_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
    except FileNotFoundError:
        log.warning(f"ensure_config: 配置文件不存在 {app_paths.CONFIG_FILE}")
        return
    except PermissionError as e:
        log.warning(f"ensure_config: 无权限读取配置文件: {e}")
        return
    except json.JSONDecodeError as e:
        log.warning(f"ensure_config: 配置文件 JSON 格式错误: {e}")
        return
    except Exception as e:
        log.warning(f"ensure_config: 读取配置文件发生意外错误: {e}")
        return

    missing_keys = [k for k in defaults if k not in file_data]
    if not missing_keys:
        return

    log.info(f"补全缺失的配置键: {missing_keys}")
    config_data = dict(defaults)
    config_data.update({k: v for k, v in file_data.items() if k not in ("api_key", "work_directory")})
    config_data["api_key"] = os.getenv("QUICKAI_API_KEY", "")
    config_data["work_directory"] = os.getenv("QUICKAI_WORK_DIRECTORY", "workplace")
    save_config(config_data)
