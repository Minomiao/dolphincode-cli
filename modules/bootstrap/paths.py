"""路径计算逻辑。由 __init__.py 的 init() 调用。"""
import os


def compute(root_path: str) -> dict:
    """根据项目根目录，计算所有数据目录及配置文件的绝对路径。"""
    date_dir = os.path.join(root_path, "date")
    return {
        "PROJECT_ROOT": root_path,
        "DATE_DIR": date_dir,
        "LOG_DIR": os.path.join(date_dir, "log"),
        "CONVERSATIONS_DIR": os.path.join(date_dir, "conversations"),
        "PROMPT_DIR": os.path.join(date_dir, "prompts"),
        "CONFIG_FILE": os.path.join(date_dir, "config.json"),
        "ENV_FILE": os.path.join(date_dir, ".env"),
        "COMMANDS_FILE": os.path.join(date_dir, "commands.json"),
        "BACKUP_DIR": os.path.join(date_dir, "backup"),
        "MODELS_DIR": os.path.join(root_path, "models"),
        "MODELS_FILE": os.path.join(date_dir, "models.json"),
    }
