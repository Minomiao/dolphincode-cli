import logging
import os
from logging.handlers import TimedRotatingFileHandler

from modules import bootstrap as app_paths
from modules.bootstrap import constants


def _ensure_log_dir() -> None:
    """确保日志目录存在。"""
    if not os.path.exists(app_paths.LOG_DIR):
        os.makedirs(app_paths.LOG_DIR)


def setup_logger(name="Dolphin", level=logging.DEBUG):
    _ensure_log_dir()

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger

    log_filepath = os.path.join(app_paths.LOG_DIR, "dolphin.log")

    # 按天轮转：跨天自动切换文件，旧日志保留 backupCount 份
    file_handler = TimedRotatingFileHandler(
        log_filepath, when="midnight", encoding='utf-8', backupCount=constants.LOG_BACKUP_COUNT
    )
    file_handler.setLevel(level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger


_thinking_logger = None

def get_thinking_logger():
    """获取思考过程专用日志 Logger"""
    global _thinking_logger
    if _thinking_logger is None:
        _ensure_log_dir()

        _thinking_logger = logging.getLogger("Dolphin.thinking")
        _thinking_logger.setLevel(logging.DEBUG)

        think_filepath = os.path.join(app_paths.LOG_DIR, "think.log")

        think_handler = TimedRotatingFileHandler(
            think_filepath, when="midnight", encoding='utf-8', backupCount=constants.LOG_BACKUP_COUNT
        )
        think_handler.setLevel(logging.DEBUG)
        think_handler.setFormatter(logging.Formatter('[%(asctime)s] 思考过程:\n%(message)s'))

        _thinking_logger.addHandler(think_handler)

    return _thinking_logger

def get_logger(name="Dolphin"):
    return logging.getLogger(name)


def log_thinking(content: str):
    """记录思考过程到专用日志文件"""
    if not content:
        return
    logger = get_thinking_logger()
    logger.debug(content)
