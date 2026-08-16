"""
项目全局固定常量。
所有模块级固定变量集中在此管理，各模块通过 from modules.bootstrap import constants 导入。
"""

# ===== 文件操作限制 =====
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
# MAX_LINE_COUNT 采用 100 行冗余设计：对外声明 1000 行，实际限制 1100 行
# 冗余用于避免创建文件再追加内容时行数统计误差导致的拒绝
MAX_LINE_COUNT = 1100
MAX_FILES_TO_READ = 1000
MAX_SEARCH_RESULTS = 500
MAX_FILES_TO_SEARCH_IN_CONTENT = 100
MAX_MATCHES_PER_FILE = 20  # 内容搜索时每个文件最多返回的匹配行数

# ===== 网页抓取限制 =====
MAX_WEB_CONTENT_LENGTH = 8000  # 单个网页内容最大字符数

# ===== 网页搜索限制 =====
WEB_SEARCH_DEFAULT_RESULTS = 15     # 默认返回结果数量

# ===== PowerShell 执行限制 =====
MAX_SCRIPT_LENGTH = 10000
MAX_OUTPUT_LENGTH = 50000
MAX_OUTPUT_LINES = 500
DEFAULT_TIMEOUT = 30
DEFAULT_WAIT_TIME = 10
# 后台进程最长存活时间（秒），超时自动清理防止泄漏
MAX_BACKGROUND_LIFETIME = 600  # 10分钟

# ===== PowerShell 缓存管理 =====
# 缓存有效期（秒）：命令完成后保留多久供 AI 轮询
COMMAND_CACHE_TTL_SECONDS = 3600  # 1小时
# 持久化缓存目录：位于 date 目录下，受 DPC 保护
COMMAND_CACHE_PERSIST_DIR = "command_cache"
# 持久化缓存清理时间（秒）：超过此时间未读取则删除
COMMAND_CACHE_PERSIST_TTL_SECONDS = 86400  # 24小时
# 最大并发缓存数量（超过时转储到持久化）
MAX_COMMAND_CACHE_SIZE = 20

DANGEROUS_PATTERNS = [
    # ===== 文件系统破坏 =====
    r'\bremove-item\b', r'\bremove-itemproperty\b',
    r'\brm\s', r'\bdel\s', r'\bdel\b', r'\brd\s', r'\brmdir\b',
    r'\bclear-content\b', r'\bclear-item\b',
    r'\bformat-volume\b', r'\bclear-disk\b', r'\binitialize-disk\b',
    r'\brename-item\b.*[-/].*path.*(?:system32|windows|boot|etc)\b',
    r'\bmove-item\b.*[-/].*destination.*(?:system32|windows|boot)\b',
    r'\bformat\s+[a-z]:', r'\bdiskpart\b',

    # ===== 进程/服务控制 =====
    r'\bstop-process\b', r'\btaskkill\b', r'\bstop-service\b',
    r'\bstart-process\b.*[-/].*(?:hidden|windowstyle\s+hidden)',

    # ===== 系统状态变更 =====
    r'\brestart-computer\b', r'\bstop-computer\b', r'\bshutdown\b',
    r'\bset-executionpolicy\b', r'\bdisable-psremoting\b', r'\benable-psremoting\b',
    r'\bset-netfirewallrule\b', r'\bset-netfirewallprofile\b',
    r'\bbcdedit\b', r'\bnetsh\b.*(?:firewall|interface|winsock)',

    # ===== 注册表修改 =====
    r'\breg\s+(add|delete|import|load|unload)\b',
    r'\bset-itemproperty\b.*(?:registry|hklm|hkcu|hkcr|hkey)',
    r'\bnew-itemproperty\b.*(?:registry|hklm|hkcu|hkcr|hkey)',
    r'\bregsvr32\b',

    # ===== 用户/权限操作 =====
    r'\bnew-localuser\b', r'\bremove-localuser\b', r'\bset-localuser\b',
    r'\badd-localgroupmember\b', r'\badd-adgroupmember\b',
    r'\bnet\s+(user|localgroup|group)\b',
    r'\bicacls\b', r'\btakeown\b', r'\battrib\b.*[+-]h',

    # ===== 计划任务/持久化 =====
    r'\bschtasks\b', r'\bnew-scheduledtask\b', r'\bregister-scheduledtask\b',
    r'\bwmic\b.*(?:startup|create\s+process)',
    r'\bsc\s+(create|delete|config|stop)',

    # ===== 代码执行/下载执行 =====
    r'\binvoke-expression\b', r'\biex\b',
    r'\binvoke-(?:webrequest|restmethod|wrmethod)\b.*\|.*\b(?:invoke-expression|iex)\b',
    r'\bwget\b.*\|.*\b(?:invoke-expression|iex|sh|bash|cmd)\b',
    r'\bcurl\b.*\|.*\b(?:invoke-expression|iex|sh|bash|cmd)\b',
    r'\bnew-object\b.*\b(?:net\.webclient|system\.net\.webclient)\b',
    r'\bnew-object\b.*\b(?:net\.sockets\.tcpclient|system\.net\.sockets)\b',
    r'\bdownloadstring\b', r'\bdownloadfile\b', r'\bdownloaddata\b',
    r'\bstart-bits transfer\b', r'\bbitsadmin\b',
    r'\bmshta\b', r'\bcertutil\b.*[-/](?:decode|encode|urlcache)',
    r'\brundll32\b',
    r'\bcscript\b', r'\bwscript\b',

    # ===== 编码/混淆执行 =====
    r'[-/](?:enc|encodedcommand|ec|e)\s+\S{20,}',
    r'\[system\.text\.encoding\].*frombase64',
    r'\bfrombase64string\b.*\binvoke-expression\b',
    r'\bfrombase64string\b.*\biex\b',
    r'\bfrombase64string\b.*\bstart-process\b',

    # ===== 解释器调用（可绕过黑名单执行任意命令）=====
    r'\b(?:python|python3|py|pyw)\s+[-/]\s*c\b',
    r'\b(?:powershell|pwsh|cmd|bash|sh|zsh)\s+[-/]\s*(?:c|k|command|encodedcommand|e)\b',

    # ===== 字符串拼接/变量拼接绕过 =====
    # 检测 "In"+"voke" 类拼接，或 [char] 拼接构造危险命令
    r'[\'"](?:i|in|inv|invo|invok|invoke)[\'"]\s*\+\s*[\'"]',
    r'\[[\s]*char[\s]*\][\s]*\d',
    r'invoke[\s]*-[\s]*expression',
    r'\bscriptblock\s*::\s*create',
    r'\.\s*\(?\s*set-itemproperty',
    r'\.\s*\(?\s*invoke-expression',
]

# ===== 上下文窗口告警阈值 =====
WARN_THRESHOLD = 0.70   # 70%: 提醒用户
HIGH_THRESHOLD = 0.85   # 85%: 建议清理
CRITICAL_THRESHOLD = 0.95  # 95%: 强烈建议清理

# ===== 工具迭代限制 =====
STREAM_MAX_HARD_LIMIT = 100
STREAM_INITIAL_MAX = 30
STREAM_EXTEND_BY = 20

# ===== DPC 对话控制文件 =====
DPC_FILENAME = ".dpc"
FILE_ATTRIBUTE_HIDDEN = 0x2

# ===== 对话恢复：文件工具集 =====
FILE_AUTOCOMPLETE_TOOLS = {"create_file", "write_file", "read_file", "modify_file", "delete_file"}
RECOVERY_WRITE_PREVIEW_LINES = 100  # 写入工具恢复时预览行数
RECOVERY_READ_LIMIT_LINES = 200    # 读取工具恢复时最大返回行数

# ===== 模型注册表 =====
MODEL_REGISTRY = {
    "deepseek-v4-flash": {
        "name": "deepseek-v4-flash",
        "description": "DeepSeek V4 Flash",
        "context_window": 1000000,
        "deprecated": False,
    },
    "deepseek-v4-pro": {
        "name": "deepseek-v4-pro",
        "description": "DeepSeek V4 Pro",
        "context_window": 1000000,
        "deprecated": False,
    },
}

# ===== API 请求超时 =====
# OpenAI SDK 默认 600s，网络故障时会让整个 CLI 冻结过久，这里收紧为 120s
API_TIMEOUT = 120

# MCP 服务器连接与工具调用超时（秒），防止 MCP 进程无响应时永久挂起
MCP_TIMEOUT = 30

# 技能/插件函数在线程中执行的最长时限（秒）
SKILL_TIMEOUT = 300

# ===== 启动动画 =====
# 启动进度条文字
DEEPSLEEPING_TEXT = "d-e-e-p-s-l-e-e-p-i-n-g"

# 终端备选屏幕控制序列
SCREEN_ALT_ENTER = '\033[?1049h'
SCREEN_ALT_EXIT = '\033[?1049l'

# Spinner 动画帧
SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

# Dolphin ASCII 艺术（5 行高度，字母逐行拼接）
_DOLPHIN_LETTERS = {
    "D": [
        " ████╗   ",
        " ██╔═██╗ ",
        " ██║ ██║ ",
        " ██╠═██║ ",
        " ████╝   ",
    ],
    "O": [
        "  ████╗  ",
        " ██╔═██╗ ",
        " ██║ ██║ ",
        " ██╠═██║ ",
        "  ████╝  ",
    ],
    "L": [
        " ██╗     ",
        " ██║     ",
        " ██║     ",
        " ██║     ",
        " ██████╗ ",
    ],
    "P": [
        " █████╗  ",
        " ██╔═██╗ ",
        " █████╔╝ ",
        " ██╔══╝  ",
        " ██║     ",
    ],
    "H": [
        " ██╗ ██╗ ",
        " ██║ ██║ ",
        " ██████║ ",
        " ██╔═██║ ",
        " ██║ ██║ ",
    ],
    "I": [
        " ██╗  ",
        " ██║  ",
        " ██║  ",
        " ██║  ",
        " ██║  ",
    ],
    "N": [
        " ███╗   ██╗ ",
        " ██╔██╗ ██║ ",
        " ██║╚██╗██║ ",
        " ██║ ╚████║ ",
        " ██║  ╚███║ ",
    ],
}


def build_dolphin_art() -> str:
    """构造 DOLPHIN 字母的 ASCII 艺术。"""
    letters = ["D", "O", "L", "P", "H", "I", "N"]
    lines = []
    for row in range(5):
        lines.append("".join(_DOLPHIN_LETTERS[L][row] for L in letters))
    return "\n".join(lines)


DOLPHIN_ART = build_dolphin_art()
