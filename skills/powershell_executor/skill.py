import re
from typing import Dict, Any


def _is_dangerous_script(script: str, patterns) -> bool:
    script_lower = script.lower()
    for pattern in patterns:
        if re.search(pattern, script_lower):
            return True
    return False


skill_info = {
    "name": "powershell_executor",
    "description": "PowerShell 脚本执行器技能，可以运行 PowerShell 命令和脚本。",
    "functions": {
        "run_script": {
            "description": "运行 PowerShell 命令或脚本。重要提示：1. 此技能会自动捕获所有输出和错误，不需要在脚本中手动实现输出捕获。2. 请使用简单直接的命令，如 'python script.py' 或 'dir'，避免生成复杂的脚本。3. 脚本长度限制为 10000 字符。4. 输出长度限制为 50000 字符。5. 命令会在工作目录下执行，使用相对路径即可访问工作区文件。6. AI 只需要调用一次函数，等待执行完成即可，不需要处理确认逻辑。7. 命令异步运行，wait_time 秒后返回当前控制台内容；若命令未完成则附带 command_id 可后续查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "PowerShell 命令或脚本内容。建议使用简单直接的命令，如 'python script.py'、'dir'、'Get-ChildItem' 等。命令会在工作目录下执行。"},
                    "timeout": {"type": "integer", "description": "超时时间（秒），默认为 30"},
                    "wait_time": {"type": "integer", "description": "等待时间（秒），默认 10。命令开始运行后等待此时间再返回结果。若命令已完成则返回完整输出，若未完成则返回当前控制台内容并附带 command_id"}
                },
                "required": ["script"]
            }
        },
        "check_script": {
            "description": "查询后台运行命令的状态和输出。若命令已完成则立即返回结果；若命令未完成，等待 wait_time 秒后返回当前状态和输出。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command_id": {"type": "string", "description": "命令 ID，由 run_script 返回"},
                    "wait_time": {"type": "integer", "description": "等待时间（秒），默认 10。命令完成则立即返回，未完成则等待此时长后返回当前状态"}
                },
                "required": ["command_id"]
            }
        },
        "kill_command": {
            "description": "强制终止后台运行的命令。返回被终止命令的最后输出内容和状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command_id": {"type": "string", "description": "命令 ID，由 run_script 返回"}
                },
                "required": ["command_id"]
            }
        }
    }
}


def run_script(context, script: str, timeout: int = None, wait_time: int = None) -> Dict[str, Any]:
    try:
        script_length = len(script)

        if script_length > context.constants.MAX_SCRIPT_LENGTH:
            context.log_warning(f"脚本过长: {script_length} 字符，最大允许: {context.constants.MAX_SCRIPT_LENGTH} 字符")
            preview = script[:500] + "..." if len(script) > 500 else script
            return {
                "error": f"脚本过长: {script_length} 字符，最大允许: {context.constants.MAX_SCRIPT_LENGTH} 字符",
                "script_length": script_length,
                "max_length": context.constants.MAX_SCRIPT_LENGTH,
                "user_output": {"label": "Run", "parts": [{"text": f"--{preview}"}, {"text": "Error", "style": "red"}]}
            }

        actual_timeout = timeout if timeout is not None else 30
        actual_wait = wait_time if wait_time is not None else 10

        context.log_info(f"AI 请求运行 PowerShell 脚本 (长度: {script_length} 字符, 超时: {actual_timeout}s, 等待: {actual_wait}s)")

        if _is_dangerous_script(script, context.constants.DANGEROUS_PATTERNS):
            script_preview = script[:500] + "..." if len(script) > 500 else script
            message = f"确认运行 PowerShell 脚本 (长度: {script_length} 字符, 超时: {actual_timeout}s, 等待: {actual_wait}s):\n{script_preview}"

            result = context.require_confirmation(
                message=message,
                action=context.constants.ACTION_RUN_POWERSHELL_SCRIPT,
                script=script,
                timeout=actual_timeout,
                wait_time=actual_wait
            )
            result["user_output"] = {"label": "Run", "parts": [{"text": f"--{script_preview}"}]}
            return result
        else:
            short_preview = script.split('\n')[0][:80]
            if len(script.split('\n')[0]) > 80:
                short_preview += "..."
            context.log_info(f"安全脚本，自动执行 (长度: {script_length} 字符)")
            return {
                "auto_execute": True,
                "action": context.constants.ACTION_RUN_POWERSHELL_SCRIPT,
                "script": script,
                "timeout": actual_timeout,
                "wait_time": actual_wait,
                "user_output": {"label": "Run", "parts": [{"text": f"--{short_preview}"}]}
            }

    except Exception as e:
        context.log_error(f"运行脚本失败: {str(e)}")
        preview = script[:500] + "..." if len(script) > 500 else script
        return {"error": f"运行脚本失败: {str(e)}", "user_output": {"label": "Run", "parts": [{"text": f"--{preview}"}, {"text": "Error", "style": "red"}]}}


async def check_script(context, command_id: str, wait_time: int = None) -> Dict[str, Any]:
    actual_wait = wait_time if wait_time is not None else 10
    result = await context.check_script(command_id, actual_wait)
    output = result.get("output", "")
    display = _truncate_output(output)
    result["user_output"] = {
        "label": "Read",
        "parts": [
            {"text": f"--{command_id}", "style": "gray"},
            {"text": display, "style": "gray"}
        ]
    }
    return result


def _truncate_output(output: str) -> str:
    output = output.rstrip('\n')
    if not output:
        return output
    lines = output.split('\n')
    if len(lines) <= 6:
        return output
    return '\n'.join(lines[:3]) + "\n..." + '\n'.join(lines[-3:])


def kill_command(context, command_id: str) -> Dict[str, Any]:
    result = context.kill_command(command_id)
    result["user_output"] = {
        "label": "Stop",
        "parts": [{"text": f"--{command_id}", "style": "gray"}]
    }
    return result
