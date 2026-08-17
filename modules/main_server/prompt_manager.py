import os
import re

from modules.logger import get_logger
from modules import bootstrap as app_paths
from .prompt_defaults import _DEFAULTS, _EFFORT_FILES, _PROMPT_FILES

log = get_logger("Dolphin.prompt_manager")


# 语言指令块模板（{language} 由 compose_system_prompt 按当前所选语言动态注入）
_LANGUAGE_BLOCK = (
    "<language>\n"
    "Always respond in {language}. Use {language} for all explanations, comments, and\n"
    "communication with the user. Technical terms and code identifiers should\n"
    "remain in their original form."
)

# 匹配 <language> 段直到下一个空行或文件末尾
_LANGUAGE_PATTERN = re.compile(r"<language>.*?(?=\n\n|\Z)", re.DOTALL)


def _with_language_block(prompt, language_name):
    """替换或追加 <language> 语言指令段，使语言与当前选择一致。

    Args:
        prompt: system.txt 内容
        language_name: 当前语言的英语名称

    Returns:
        注入语言指令后的完整提示词
    """
    block = _LANGUAGE_BLOCK.format(language=language_name)
    if "<language>" in prompt:
        return _LANGUAGE_PATTERN.sub(block, prompt, count=1)
    return prompt.rstrip() + "\n\n" + block


# 每轮动态提醒追加的语言准则块（{language} 按当前所选语言注入）
_TURN_LANGUAGE_BLOCK = (
    "<language>\n"
    "Reply to the user in {language}. Write all explanations, comments, and\n"
    "communication in {language}. Technical terms and code identifiers remain\n"
    "in their original form."
)

# 特殊语言风格指导（仅对特定语言注入，key 为语言代码）
_LANGUAGE_STYLE_GUIDES = {
    "wenyan": (
        "<style>\n"
        "Respond in a Classical Chinese (文言文) register: use classical pronouns\n"
        "and particles (吾, 汝, 之, 乎, 者, 也), keep sentences concise and\n"
        "dignified, and avoid modern colloquialisms and internet slang. Technical\n"
        "terms and code identifiers stay in their original form."
    ),
    "nyannyan": (
        "<style>\n"
        "Respond in a playful cat-speak style (喵喵語): sprinkle meow particles\n"
        "(喵~, nya~) naturally into the sentences, use light and cute wording,\n"
        "while keeping the meaning clear. Technical terms and code identifiers\n"
        "stay in their original form."
    ),
}


class PromptManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PromptManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """初始化提示词管理器"""
        if not os.path.exists(app_paths.PROMPT_DIR):
            os.makedirs(app_paths.PROMPT_DIR)
            log.info(f"创建提示词目录: {app_paths.PROMPT_DIR}")

        self._ensure_default_files()
        self.prompts = self._load_prompts()
        self.effort_prompts = self._load_effort_prompts()
        log.info(f"提示词管理器初始化完成，加载了 {len(self.prompts)} 个提示词")

    # ---- 文件管理 ----

    def _ensure_default_files(self):
        """确保默认提示词文件存在，不存在则创建"""
        for filename, content in _DEFAULTS.items():
            filepath = os.path.join(app_paths.PROMPT_DIR, filename)
            if not os.path.exists(filepath):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                log.info(f"创建默认提示词文件: {filepath}")

    @staticmethod
    def _read_file(filepath):
        """读取单个提示词文件，返回内容字符串"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            log.warning(f"提示词文件不存在: {filepath}")
            return ""
        except Exception as e:
            log.error(f"读取提示词文件失败 {filepath}: {e}")
            return ""

    @staticmethod
    def _write_file(filepath, content):
        """写入单个提示词文件"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            log.debug(f"保存提示词到: {filepath}")
            return True
        except Exception as e:
            log.error(f"保存提示词失败 {filepath}: {e}")
            return False

    # ---- 加载 ----

    def _load_prompts(self):
        """加载核心提示词文件（system / work_directory / directory_structure）"""
        prompts = {}
        for key, filename in _PROMPT_FILES.items():
            filepath = os.path.join(app_paths.PROMPT_DIR, filename)
            prompts[key] = self._read_file(filepath)
        return prompts

    def _load_effort_prompts(self):
        """加载思考深度提示词文件（effort_fine / effort_normal / effort_high）"""
        effort_prompts = {}
        for key, filename in _EFFORT_FILES.items():
            filepath = os.path.join(app_paths.PROMPT_DIR, filename)
            effort_prompts[key] = self._read_file(filepath)
        return effort_prompts

    # ---- 提示词获取与组合 ----

    def get_prompt(self, prompt_key, **kwargs):
        """获取单个提示词，支持 format 占位符替换"""
        prompt = self.prompts.get(prompt_key, "")
        if prompt and kwargs:
            try:
                prompt = prompt.format(**kwargs)
            except Exception as e:
                log.error(f"格式化提示词失败: {e}")
        return prompt

    def compose_system_prompt(self):
        """返回系统提示词，语言指令段随当前所选显示语言动态拼接。

        已存在的旧版 system.txt（硬编码 Chinese）也会被替换为当前语言；
        若文件中无 <language> 段则在末尾追加。
        """
        prompt = self.prompts.get("system", "")
        from modules.CLIserver import i18n
        return _with_language_block(prompt, i18n.get_language_instruction_name())

    def compose_context(self, **kwargs):
        """组合每轮动态上下文 (turn_reminder + work_directory + directory_structure + effort)。

        turn_reminder 会追加当前所选语言的语言准则，特殊语言（文言文、
        喵喵語等）再附加对应风格指导。
        """
        effort_level = kwargs.pop("effort_level", "fine")
        effort_prompt = self.effort_prompts.get(effort_level, "")

        from modules.CLIserver import i18n
        language_code = i18n.get_language()
        language_name = i18n.get_language_instruction_name()

        turn_reminder = self.prompts.get("turn_reminder", "")
        parts = [turn_reminder, _TURN_LANGUAGE_BLOCK.format(language=language_name)]
        style_guide = _LANGUAGE_STYLE_GUIDES.get(language_code)
        if style_guide:
            parts.append(style_guide)

        parts += [
            self.get_prompt("work_directory", **kwargs),
            self.get_prompt("directory_structure", **kwargs),
            effort_prompt,
        ]
        return "\n\n".join(p for p in parts if p)

    # ---- 提示词修改 ----

    def set_prompt(self, prompt_key, prompt_content):
        """设置提示词并持久化到对应 txt 文件"""
        # 尝试写入核心提示词文件
        filename = _PROMPT_FILES.get(prompt_key)
        if filename:
            filepath = os.path.join(app_paths.PROMPT_DIR, filename)
            if self._write_file(filepath, prompt_content):
                self.prompts[prompt_key] = prompt_content
                log.info(f"更新提示词: {prompt_key}")
                return

        # 尝试写入努力程度提示词文件
        filename = _EFFORT_FILES.get(prompt_key)
        if filename:
            filepath = os.path.join(app_paths.PROMPT_DIR, filename)
            if self._write_file(filepath, prompt_content):
                self.effort_prompts[prompt_key] = prompt_content
                log.info(f"更新努力程度提示词: {prompt_key}")
                return

        log.warning(f"未知的提示词键: {prompt_key}")

    # ---- 请求处理 ----

    def handle_request(self, request):
        """处理提示词请求，支持 prompt_request / get_prompt / set_prompt 三种类型"""
        request_type = request.get("type")

        if request_type == "prompt_request":
            prompt_key = request.get("prompt_key")
            kwargs = request.get("kwargs", {})

            if prompt_key == "system":
                prompt = self.compose_system_prompt()
            elif prompt_key == "context":
                prompt = self.compose_context(**kwargs)
            else:
                prompt = self.get_prompt(prompt_key, **kwargs)

            return {
                "success": True,
                "prompt": prompt,
                "prompt_key": prompt_key
            }

        elif request_type == "get_prompt":
            prompt_key = request.get("prompt_key")
            if not prompt_key:
                return {"error": "缺少 prompt_key"}
            kwargs = request.get("kwargs", {})
            prompt = self.get_prompt(prompt_key, **kwargs)
            return {
                "success": True,
                "prompt": prompt,
                "prompt_key": prompt_key
            }

        elif request_type == "set_prompt":
            prompt_key = request.get("prompt_key")
            prompt_content = request.get("prompt_content")
            if not prompt_key or prompt_content is None:
                return {"error": "缺少 prompt_key 或 prompt_content"}
            self.set_prompt(prompt_key, prompt_content)
            return {
                "success": True,
                "prompt_key": prompt_key
            }

        else:
            return {"error": "未知的请求类型"}


def get_prompt_manager():
    """获取提示词管理器实例"""
    return PromptManager()
