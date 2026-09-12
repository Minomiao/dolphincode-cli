"""国际化：语言注册表、翻译表与翻译查询接口。

界面文案统一通过 t() 获取，未翻译的键回退到简体中文。
翻译表内置在 modules.bootstrap.translations 中；启动时同步到 date/language/ 目录
（每种语言一个 {code}.json 文件），之后从这些文件加载（可直接编辑自定义文案）。
内置文案版本变化时（TRANSLATIONS_VERSION 递增）会刷新语言文件，
旧文件备份为 {code}.json.bak，用户自行新增的键始终保留。
新增语言只需在 SUPPORTED_LANGUAGES 中注册，并在 modules.bootstrap.translations 中补充翻译。
"""
import json
import os
import shutil

from modules.logger import get_logger
from modules.bootstrap.translations import TRANSLATIONS as _BUILTIN_TRANSLATIONS
from modules.bootstrap.translations import TRANSLATIONS_VERSION as _BUILTIN_VERSION

log = get_logger("Dolphin.i18n")

DEFAULT_LANGUAGE = "zh-CN"

# 支持的语言列表（native 为母语名称，用于语言选择界面）
SUPPORTED_LANGUAGES = [
    # 东亚
    {"code": "zh-CN", "native": "简体中文"},
    {"code": "zh-TW", "native": "繁體中文"},
    {"code": "ja-JP", "native": "日本語"},
    {"code": "ko-KR", "native": "한국어"},
    # 欧洲
    {"code": "en-US", "native": "English"},
    {"code": "fr-FR", "native": "Français"},
    {"code": "de-DE", "native": "Deutsch"},
    {"code": "es-ES", "native": "Español"},
    {"code": "pt-BR", "native": "Português"},
    {"code": "it-IT", "native": "Italiano"},
    {"code": "ru-RU", "native": "Русский"},
    {"code": "nl-NL", "native": "Nederlands"},
    {"code": "pl-PL", "native": "Polski"},
    {"code": "sv-SE", "native": "Svenska"},
    {"code": "cs-CZ", "native": "Čeština"},
    {"code": "hu-HU", "native": "Magyar"},
    {"code": "ro-RO", "native": "Română"},
    {"code": "da-DK", "native": "Dansk"},
    {"code": "fi-FI", "native": "Suomi"},
    {"code": "nb-NO", "native": "Norsk"},
    {"code": "el-GR", "native": "Ελληνικά"},
    {"code": "bg-BG", "native": "Български"},
    {"code": "sr-RS", "native": "Српски"},
    {"code": "lt-LT", "native": "Lietuvių"},
    # 中东/中亚
    {"code": "tr-TR", "native": "Türkçe"},
    {"code": "ar-SA", "native": "العربية"},
    {"code": "he-IL", "native": "עברית"},
    {"code": "fa-IR", "native": "فارسی"},
    # 南亚/东南亚
    {"code": "hi-IN", "native": "हिन्दी"},
    {"code": "bn-BD", "native": "বাংলা"},
    {"code": "th-TH", "native": "ไทย"},
    {"code": "vi-VN", "native": "Tiếng Việt"},
    {"code": "id-ID", "native": "Bahasa Indonesia"},
    {"code": "ms-MY", "native": "Bahasa Melayu"},
    {"code": "tl-PH", "native": "Tagalog"},
    # 非洲
    {"code": "sw-KE", "native": "Kiswahili"},
    # 高加索
    {"code": "ka-GE", "native": "ქართული"},
    {"code": "uk-UA", "native": "Українська"},
    # 特殊语言
    {"code": "wenyan", "native": "文言文"},
    {"code": "nyannyan", "native": "喵喵語 (=^･ω･^=)"},
]

# 语言代码 → 英语语言名（用于系统提示词中的语言指令，随所选语言切换）
LANGUAGE_INSTRUCTION_NAMES = {
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "en-US": "English",
    "fr-FR": "French",
    "de-DE": "German",
    "es-ES": "Spanish",
    "pt-BR": "Portuguese",
    "it-IT": "Italian",
    "ru-RU": "Russian",
    "nl-NL": "Dutch",
    "pl-PL": "Polish",
    "sv-SE": "Swedish",
    "cs-CZ": "Czech",
    "hu-HU": "Hungarian",
    "ro-RO": "Romanian",
    "da-DK": "Danish",
    "fi-FI": "Finnish",
    "nb-NO": "Norwegian",
    "el-GR": "Greek",
    "bg-BG": "Bulgarian",
    "sr-RS": "Serbian",
    "lt-LT": "Lithuanian",
    "tr-TR": "Turkish",
    "ar-SA": "Arabic",
    "he-IL": "Hebrew",
    "fa-IR": "Persian",
    "hi-IN": "Hindi",
    "bn-BD": "Bengali",
    "th-TH": "Thai",
    "vi-VN": "Vietnamese",
    "id-ID": "Indonesian",
    "ms-MY": "Malay",
    "tl-PH": "Tagalog",
    "sw-KE": "Swahili",
    "ka-GE": "Georgian",
    "uk-UA": "Ukrainian",
    "wenyan": "Classical Chinese",
    "nyannyan": "Nyan (meow) language",
}

_active_language = DEFAULT_LANGUAGE
_translations = _BUILTIN_TRANSLATIONS


def _get_language_dir():
    """返回语言数据目录（date/language）的绝对路径。"""
    from modules.bootstrap import DATE_DIR
    return os.path.join(DATE_DIR, "language")


_VERSION_KEY = "_version"


def _write_json_file(path, data):
    """以 UTF-8 写入 JSON 数据文件，自动创建父目录。"""
    dirpath = os.path.dirname(path)
    if dirpath and not os.path.exists(dirpath):
        os.makedirs(dirpath)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_language_file(path):
    """读取语言文件，失败时返回空字典。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except PermissionError as e:
        log.warning(f"无权限读取语言文件 {path}: {e}")
    except json.JSONDecodeError as e:
        log.warning(f"语言文件格式错误 {path}: {e}")
    except Exception as e:
        log.warning(f"读取语言文件发生意外错误 {path}: {e}")
    return {}


def _backup_language_file(path):
    """刷新前把旧语言文件备份为 .bak，便于找回自定义文案。"""
    try:
        shutil.copyfile(path, path + ".bak")
    except (OSError, PermissionError) as e:
        log.warning(f"备份语言文件失败 {path}: {e}")


def _sync_language_file(path, table, data):
    """同步单个语言文件，返回可直接使用的键值表。

    - 版本一致：文件优先，允许用户自定义既有文案
    - 文件缺失或版本落后：以内置文案刷新文件（旧文件备份为 .bak），
      用户自行新增的键（内置表里没有的）始终保留
    """
    extras = {k: v for k, v in data.items() if k not in table and k != _VERSION_KEY}
    if data.get(_VERSION_KEY) == _BUILTIN_VERSION:
        return {**table, **{k: v for k, v in data.items() if k != _VERSION_KEY}}

    if os.path.exists(path):
        _backup_language_file(path)
    if not data:
        log.info(f"已生成语言文件: {path}")
    else:
        log.info(f"已刷新语言文件（内置文案版本 {_BUILTIN_VERSION}）: {path}")
    try:
        _write_json_file(path, {_VERSION_KEY: _BUILTIN_VERSION, **table, **extras})
    except (OSError, PermissionError) as e:
        log.warning(f"写入语言文件失败 {path}: {e}")
    return {**table, **extras}


def _load_translations():
    """启动时同步语言数据目录并加载翻译表。

    每种语言对应 date/language/{code}.json 一个文件：首次运行时生成，
    之后从文件加载并与内置表合并（文件优先），便于单独编辑每种语言；
    内置文案版本变化时会刷新文件，避免旧文件盖住更新后的文案。
    """
    global _translations
    lang_dir = _get_language_dir()
    merged = {}
    try:
        if not os.path.exists(lang_dir):
            os.makedirs(lang_dir)
        for code, table in _BUILTIN_TRANSLATIONS.items():
            lang_file = os.path.join(lang_dir, f"{code}.json")
            data = _read_language_file(lang_file) if os.path.exists(lang_file) else {}
            merged[code] = _sync_language_file(lang_file, table, data)
        _translations = merged
        log.info(f"已从语言数据目录加载翻译: {lang_dir}")
    except Exception as e:
        log.warning(f"加载语言数据目录发生意外错误，使用内置翻译表: {e}")
        _translations = _BUILTIN_TRANSLATIONS


def init(language_code=None):
    """初始化/切换当前显示语言。

    Args:
        language_code: 语言代码（如 'zh-CN'）；无效或未指定时使用默认语言
    """
    global _active_language
    _load_translations()
    code = language_code or DEFAULT_LANGUAGE
    supported = [lang["code"] for lang in SUPPORTED_LANGUAGES]
    if code not in supported:
        log.warning(f"不支持的显示语言: {code}，回退到 {DEFAULT_LANGUAGE}")
        code = DEFAULT_LANGUAGE
    _active_language = code
    log.info(f"显示语言: {code}")


def get_language():
    """返回当前显示语言代码。"""
    return _active_language


def get_supported_languages():
    """返回支持的语言列表（含母语名称）。"""
    return list(SUPPORTED_LANGUAGES)


def get_language_instruction_name():
    """返回当前语言的英语名称，用于系统提示词中的语言指令。

    Returns:
        英语语言名；未注册的语言回退到默认语言名称
    """
    return (LANGUAGE_INSTRUCTION_NAMES.get(_active_language)
            or LANGUAGE_INSTRUCTION_NAMES[DEFAULT_LANGUAGE])


def t(key, **kwargs):
    """按当前语言获取界面文案。

    Args:
        key: 翻译键
        kwargs: 格式化参数（如 name='English'）

    Returns:
        翻译文本；当前语言未命中时回退简体中文，仍未命中返回原键
    """
    text = (_translations.get(_active_language, {}).get(key)
            or _translations.get(DEFAULT_LANGUAGE, {}).get(key)
            or key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
