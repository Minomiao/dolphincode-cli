"""
程序启动引导模块。
由 main.py 在启动之初调用 bootstrap.init(root_path) 完成路径初始化。
支持 PyInstaller 打包后的路径解析。
"""
from .paths import compute

PROJECT_ROOT = None
DATE_DIR = None
LOG_DIR = None
CONVERSATIONS_DIR = None
PROMPT_DIR = None
CONFIG_FILE = None
ENV_FILE = None
COMMANDS_FILE = None
BACKUP_DIR = None
MODELS_DIR = None
CUSTOM_MODELS_FILE = None


def _init_date_dpc():
    """初始化 date 目录的 DPC 保护，避免 logger 模块与 dpc_manager 循环依赖。"""
    try:
        from modules.chater import dpc_manager
        dpc_manager.ensure_restriction(DATE_DIR, ["*"])
    except Exception as e:
        import logging
        logging.getLogger("Dolphin.bootstrap").error(f"DPC 初始化失败: {e}")


def init(root_path: str):
    """由 main.py 调用，传入项目根目录绝对路径。"""
    global PROJECT_ROOT, DATE_DIR, LOG_DIR
    global CONVERSATIONS_DIR, PROMPT_DIR
    global CONFIG_FILE, ENV_FILE, COMMANDS_FILE
    global MODELS_DIR, CUSTOM_MODELS_FILE

    if PROJECT_ROOT is not None:
        return

    globals().update(compute(root_path))
    _init_date_dpc()
