import os
import json
from modules.logger import get_logger
from modules import bootstrap as app_paths

log = get_logger("Dolphin.commands")


def init():
    """显式初始化命令模块：校验并修复命令文件。

    由 main.py 在启动时调用一次，避免模块导入时产生副作用。
    """
    _validate_commands()


def _get_default_commands():
    return {
        "commands": {
            "set": {
                "input": "set",
                "description": "进入设置模式"
            },
            "back": {
                "input": "back",
                "description": "返回 (在设置模式中使用)"
            },
            "help": {
                "input": "help",
                "description": "显示此帮助信息"
            },
            "quit": {
                "input": "quit",
                "description": "退出程序"
            },
            "clear": {
                "input": "clear",
                "description": "清空对话历史"
            },
            "new": {
                "input": "new",
                "description": "开启新对话"
            },
            "load": {
                "input": "load",
                "description": "加载旧对话"
            },
            "list": {
                "input": "list",
                "description": "查看所有对话"
            },
            "tools": {
                "input": "tools",
                "description": "查看可用工具"
            },
            "skills": {
                "input": "skills",
                "description": "查看可用技能"
            },
            "toggle": {
                "input": "toggle",
                "description": "切换工具启用/禁用状态"
            },
            "open": {
                "input": "workdir",
                "description": "打开/切换工作目录"
            },
            "model": {
                "input": "model",
                "description": "切换模型和配置 API 密钥"
            },
            "language": {
                "input": "language",
                "description": "选择显示语言"
            },
            "showthinking": {
                "input": "showthinking",
                "description": "显示/隐藏 AI 思考过程 (on/off)"
            },
            "effort": {
                "input": "effort",
                "description": "设置 AI 思考深度 (fine/normal/high)"
            },
            "changes": {
                "input": "changes",
                "description": "处理待处理的文件变更"
            }
        }
    }


def _get_prefix():
    config_path = app_paths.CONFIG_FILE
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            return config_data.get("command_prefix", "/")
        except Exception as e:
            log.debug(f"读取命令前缀失败: {e}")
    return "/"


def _validate_commands():
    if not os.path.exists(app_paths.COMMANDS_FILE):
        return

    try:
        with open(app_paths.COMMANDS_FILE, 'r', encoding='utf-8') as f:
            file_data = json.load(f)
    except Exception as e:
        log.warning(f"读取命令文件失败，跳过校验: {e}")
        return

    file_commands = file_data.get("commands", {})
    if not file_commands:
        return

    defaults = _get_default_commands()
    default_commands = defaults["commands"]
    changed = False

    for key, default_info in default_commands.items():
        expected_keyword = default_info["input"]
        if key in file_commands:
            current_keyword = file_commands[key].get("input", "")
            if current_keyword != expected_keyword:
                log.warning(f"命令 '{key}' 关键词异常 (当前: '{current_keyword}', 期望: '{expected_keyword}')，已自动修复")
                file_commands[key]["input"] = expected_keyword
                changed = True
        else:
            file_commands[key] = {
                "input": default_info["input"],
                "description": default_info["description"]
            }
            log.info(f"命令 '{key}' 缺失，已自动添加")
            changed = True

    if changed:
        with open(app_paths.COMMANDS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"commands": file_commands}, f, ensure_ascii=False, indent=2)
        log.info("命令文件校验完成，已修复异常项")


def load_commands():
    prefix = _get_prefix()
    resolved = {"commands": {}}

    keywords = {}
    if os.path.exists(app_paths.COMMANDS_FILE):
        try:
            with open(app_paths.COMMANDS_FILE, 'r', encoding='utf-8') as f:
                file_data = json.load(f)
            for key, info in file_data.get("commands", {}).items():
                keywords[key] = info.get("input", key)
        except Exception as e:
            log.warning(f"读取命令文件失败: {e}")

    defaults = _get_default_commands()
    for key, info in defaults["commands"].items():
        keyword = keywords.get(key, info["input"])
        resolved["commands"][key] = {
            "input": prefix + keyword,
            "description": info["description"]
        }
    return resolved


def save_commands(prefix=None):
    if prefix is not None:
        if os.path.exists(app_paths.CONFIG_FILE):
            try:
                with open(app_paths.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                log.warning(f"读取配置文件失败: {e}")
                config_data = {}
        else:
            config_data = {}
        config_data["command_prefix"] = prefix
        if not os.path.exists(app_paths.DATE_DIR):
            os.makedirs(app_paths.DATE_DIR)
        with open(app_paths.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        log.info(f"命令前缀已保存: {prefix}")

    existing_commands = {}
    if os.path.exists(app_paths.COMMANDS_FILE):
        try:
            with open(app_paths.COMMANDS_FILE, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            existing_commands = existing_data.get("commands", {})
        except Exception as e:
            log.warning(f"读取现有命令文件失败: {e}")

    defaults = _get_default_commands()
    resolved = {"commands": {}}

    for key, info in defaults["commands"].items():
        resolved["commands"][key] = {
            "input": info["input"],
            "description": info["description"]
        }

    for key, info in existing_commands.items():
        if key not in resolved["commands"]:
            resolved["commands"][key] = info

    if not os.path.exists(app_paths.DATE_DIR):
        os.makedirs(app_paths.DATE_DIR)
    with open(app_paths.COMMANDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(resolved, f, ensure_ascii=False, indent=2)
    log.debug(f"已生成帮助文件: {app_paths.COMMANDS_FILE}")


def get_command(cmd_key):
    prefix = _get_prefix()
    defaults = _get_default_commands()
    cmd_list = defaults.get("commands", {})
    if cmd_key in cmd_list:
        return prefix + cmd_list[cmd_key].get("input", cmd_key)
    return prefix + cmd_key


def get_command_keyword(cmd_key):
    """返回命令的关键词（不含前缀），用于匹配用户输入。

    Args:
        cmd_key: 命令键名（如 'help', 'set', 'model'）

    Returns:
        命令关键词（如 'help', 'set', 'model'）
    """
    defaults = _get_default_commands()
    cmd_list = defaults.get("commands", {})
    if cmd_key in cmd_list:
        return cmd_list[cmd_key].get("input", cmd_key)
    return cmd_key


def get_command_description(cmd_key):
    defaults = _get_default_commands()
    cmd_list = defaults.get("commands", {})
    if cmd_key in cmd_list:
        return cmd_list[cmd_key].get("description", "")
    return ""
