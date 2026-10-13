import sys
import asyncio
import time
import atexit
import signal
import base64
import json
import os
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timedelta

from modules.logger import get_logger
from modules.bootstrap import constants
from modules.functions.command_cache import get_command_cache_manager

log = get_logger("Dolphin.powershell_manager")

_running_processes: Dict[str, Dict[str, Any]] = {}
_process_counter = 0
# 后台自动清理任务集合：保存引用避免任务被 GC 时产生 "Task was destroyed" 警告
_bg_cleanup_tasks: set = set()
# 退出信号是否已处理，防止重复触发
_shutdown_started = False


def init():
    """显式初始化 PowerShell 管理模块：清理持久化缓存、注册退出清理与信号处理。

    由 main.py 在启动时调用一次，避免模块导入时产生副作用。
    """
    get_command_cache_manager().cleanup_expired_persistent(force_all=True)
    atexit.register(_cleanup_all_processes)
    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, AttributeError):
        pass
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, AttributeError):
        pass


class _DummySock:
    def close(self):
        pass

    def fileno(self):
        return -1


def _get_work_dir():
    """获取 PowerShell 命令执行的工作目录，失败时回退为 'workplace'。"""
    try:
        from modules.main_server import config
        return config.load_config().get('work_directory', 'workplace')
    except Exception:
        return 'workplace'


async def _read_stream(stream: asyncio.StreamReader, buffer: list, max_chars: int = constants.MAX_OUTPUT_LENGTH):
    """读取流内容到缓冲区，最多读取 max_chars 个字符。"""
    total = 0
    while total < max_chars:
        try:
            line = await stream.readline()
        except Exception as e:
            log.warning(f"读取进程输出流失败: {e}")
            break
        if not line:
            break
        try:
            decoded = line.decode('utf-8', errors='ignore')
        except Exception:
            decoded = line.decode('ascii', errors='ignore')
        buffer.append(decoded)
        total += len(decoded)


def _close_transports(proc_info: dict) -> None:
    """关闭进程相关传输并取消读取任务，避免连接泄漏。"""
    process = proc_info['process']
    try:
        proc_info['stdout_task'].cancel()
    except Exception:
        pass
    try:
        proc_info['stderr_task'].cancel()
    except Exception:
        pass
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(process, stream_name, None)
        if stream is not None:
            try:
                tr = getattr(stream, '_transport', None)
                if tr is not None:
                    try:
                        tr.close()
                    except Exception:
                        pass
                    try:
                        tr._sock = _DummySock()
                    except Exception:
                        pass
            except Exception:
                pass
    try:
        if hasattr(process, '_transport') and process._transport is not None:
            try:
                process._transport.close()
            except Exception:
                pass
            try:
                process._transport._sock = _DummySock()
            except Exception:
                pass
    except Exception:
        pass


async def _wait_for_task_with_timeout(task: asyncio.Task, name: str, command_id: str, timeout: int = 30) -> None:
    """等待异步任务完成，超时则 cancel 防止永久挂起。

    兼容取消竞态：若内层读取任务被外部清理（_auto_kill_background/_close_transports）
    抢先取消，视为任务已完成，避免 CancelledError 向上击穿整个调用链。
    """
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        log.warning(f"Task {name} 超时 {timeout}s: command_id={command_id}, 取消任务")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling() > 0:
            raise  # 外层任务自身被取消（如 Ctrl+C），正常传播
        # 内层任务被外部清理取消（竞态），视为已完成
        log.debug(f"Task {name} 已被外部取消，视为完成: command_id={command_id}")
        return


async def _auto_kill_background(command_id: str, delay: int = constants.MAX_BACKGROUND_LIFETIME) -> None:
    """后台进程超时自动清理，防止进程/任务永久泄漏"""
    await asyncio.sleep(delay)
    if command_id not in _running_processes:
        return
    log.warning(f"后台进程超过最大存活时间 {delay}s, 自动终止: command_id={command_id}")
    try:
        proc_info = _running_processes[command_id]
        _close_transports(proc_info)
        try:
            proc_info['process'].kill()
        except Exception:
            pass
        del _running_processes[command_id]
    except Exception as e:
        log.error(f"后台进程自动清理失败: command_id={command_id}, {e}")


def _format_result_output(stdout: str, stderr: str, exit_code: Optional[int]) -> str:
    """格式化命令执行结果：非零退出码或 stdout 为空时附带 stderr。

    脚本错误通常写入 stderr，若结果仅含 stdout，AI 无法看到失败原因。
    stderr 非空时以 [stderr] 区块附加在输出末尾。
    """
    if exit_code == 0 and stdout.strip():
        return stdout
    stderr = stderr.strip()
    if not stderr:
        return stdout
    separator = "" if stdout.endswith("\n") else "\n"
    return f"{stdout}{separator}[stderr]\n{stderr}"


async def execute_script(script: str, timeout: int = constants.DEFAULT_TIMEOUT, wait_time: int = constants.DEFAULT_WAIT_TIME) -> Dict[str, Any]:
    global _process_counter
    _process_counter += 1
    command_id = f"dps{_process_counter:04d}"

    work_dir = _get_work_dir()
    work_path = Path(work_dir).resolve()
    if not work_path.exists():
        work_path.mkdir(parents=True, exist_ok=True)

    log.info(f"执行脚本: command_id={command_id}, timeout={timeout}s, wait={wait_time}s")
    exec_start = time.time()

    try:
        process = await _start_process(script, work_path, command_id)

        proc_info = {
            'process': process,
            'script': script[:200],
            'start_time': time.time(),
            'stdout_task': None,
            'stderr_task': None,
            'stdout_buffer': [],
            'stderr_buffer': [],
        }

        stdout_buffer: list = []
        stderr_buffer: list = []
        stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_buffer))
        stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_buffer))
        proc_info['stdout_task'] = stdout_task
        proc_info['stderr_task'] = stderr_task
        proc_info['stdout_buffer'] = stdout_buffer
        proc_info['stderr_buffer'] = stderr_buffer

        _running_processes[command_id] = proc_info

        try:
            await asyncio.wait_for(process.wait(), timeout=wait_time)
            await _wait_for_task_with_timeout(stdout_task, "stdout", command_id)
            await _wait_for_task_with_timeout(stderr_task, "stderr", command_id)

            stdout = ''.join(stdout_buffer)
            stderr = ''.join(stderr_buffer)
            if len(stdout) > constants.MAX_OUTPUT_LENGTH:
                stdout = stdout[:constants.MAX_OUTPUT_LENGTH] + f"\n... (输出已截断)"
            if len(stderr) > constants.MAX_OUTPUT_LENGTH:
                stderr = stderr[:constants.MAX_OUTPUT_LENGTH] + f"\n... (stderr 已截断)"
            merged_output = _format_result_output(stdout, stderr, process.returncode)

            _close_transports(proc_info)
            # 使用新的缓存管理器（带 TTL）
            get_command_cache_manager().add(command_id, {
                "status": "done",
                "exit_code": process.returncode,
                "output": merged_output
            })
            _running_processes.pop(command_id, None)

            elapsed = time.time() - exec_start
            log.info(f"命令完成: command_id={command_id}, returncode={process.returncode}, 耗时={elapsed:.3f}s")

            return {
                "success": True,
                "return_code": process.returncode,
                "output": merged_output,
                "completed": True,
                "command_id": command_id,
                "message": f"脚本执行完成，返回码: {process.returncode}"
            }

        except asyncio.TimeoutError:
            await asyncio.sleep(0.1)
            stdout = ''.join(stdout_buffer)
            stderr = ''.join(stderr_buffer)
            merged_output = _format_result_output(stdout, stderr, None)

            # 注册后台超时自动清理：后台存活不超过 timeout（至少 wait_time），防止进程永久泄漏
            task = asyncio.create_task(_auto_kill_background(command_id, delay=max(timeout, wait_time)))
            # 保存引用，避免任务被 GC 时产生 "Task was destroyed but it is pending!" 警告
            _bg_cleanup_tasks.add(task)
            task.add_done_callback(_bg_cleanup_tasks.discard)

            elapsed = time.time() - exec_start
            log.info(f"命令仍在运行: command_id={command_id}, stdout={len(stdout)}字, 已耗时={elapsed:.3f}s")

            return {
                "success": True,
                "output": merged_output if merged_output else "(命令正在运行中...)",
                "completed": False,
                "command_id": command_id,
                "wait_time": wait_time,
                "message": f"命令仍在后台运行中 (command_id: {command_id})，可使用 check_script 查询最新输出"
            }

    except Exception as e:
        log.error(f"执行脚本失败: command_id={command_id}, error={str(e)}")
        if command_id in _running_processes:
            _close_transports(_running_processes[command_id])
            del _running_processes[command_id]
        # 使用新的缓存管理器记录错误状态
        get_command_cache_manager().add(command_id, {
            "status": "done",
            "exit_code": None,
            "output": ""
        })
        return {"error": f"命令执行失败: {str(e)}", "command_id": command_id, "output": ""}


async def check_script(command_id: str, wait_time: int = constants.DEFAULT_WAIT_TIME) -> Dict[str, Any]:
    # 先检查缓存（使用新的缓存管理器，支持 TTL）
    cached_result = get_command_cache_manager().get(command_id)
    if cached_result is not None:
        return cached_result
    
    if command_id not in _running_processes:
        return {
            "status": "done",
            "exit_code": None,
            "output": ""
        }

    proc_info = _running_processes[command_id]
    process = proc_info['process']

    log.info(f"check_script: command_id={command_id}, wait={wait_time}s")
    check_start = time.time()

    try:
        await asyncio.wait_for(process.wait(), timeout=wait_time)
        await _wait_for_task_with_timeout(proc_info['stdout_task'], "stdout", command_id)
        await _wait_for_task_with_timeout(proc_info['stderr_task'], "stderr", command_id)

        stdout = ''.join(proc_info['stdout_buffer'])
        stderr = ''.join(proc_info['stderr_buffer'])
        return_code = process.returncode
        merged_output = _format_result_output(stdout, stderr, return_code)

        lines = merged_output.split('\n')
        if len(lines) > constants.MAX_OUTPUT_LINES:
            merged_output = '\n'.join(lines[-constants.MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

        _close_transports(proc_info)
        # 使用新的缓存管理器
        get_command_cache_manager().add(command_id, {
            "status": "done",
            "exit_code": return_code,
            "output": merged_output
        })
        _running_processes.pop(command_id, None)

        elapsed = time.time() - check_start
        log.info(f"命令完成: command_id={command_id}, returncode={return_code}, 耗时={elapsed:.3f}s")

        return {
            "status": "done",
            "exit_code": return_code,
            "output": merged_output
        }

    except asyncio.TimeoutError:
        await asyncio.sleep(0.1)
        stdout = ''.join(proc_info['stdout_buffer'])
        stderr = ''.join(proc_info['stderr_buffer'])
        merged_output = _format_result_output(stdout, stderr, None)

        lines = merged_output.split('\n')
        if len(lines) > constants.MAX_OUTPUT_LINES:
            merged_output = '\n'.join(lines[-constants.MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

        elapsed = time.time() - check_start
        log.info(f"命令仍在运行: command_id={command_id}, 已耗时={elapsed:.3f}s")

        return {
            "status": "running",
            "output": merged_output if merged_output else "(命令正在运行中...)"
        }


def kill_command(command_id: str) -> Dict[str, Any]:
    """强制终止指定命令的后台进程并返回其输出。"""
    # 先检查缓存
    cached_result = get_command_cache_manager().get(command_id)
    if cached_result is not None:
        return cached_result
    
    if command_id not in _running_processes:
        return {
            "status": "done",
            "exit_code": None,
            "output": ""
        }

    proc_info = _running_processes[command_id]
    process = proc_info['process']

    _close_transports(proc_info)

    try:
        process.kill()
    except Exception as e:
        log.error(f"终止进程失败: command_id={command_id}, error={str(e)}")

    stdout = ''.join(proc_info['stdout_buffer'])
    stderr = ''.join(proc_info['stderr_buffer'])
    exit_code = process.returncode
    merged_output = _format_result_output(stdout, stderr, exit_code)

    lines = merged_output.split('\n')
    if len(lines) > constants.MAX_OUTPUT_LINES:
        merged_output = '\n'.join(lines[-constants.MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

    # 使用新的缓存管理器
    get_command_cache_manager().add(command_id, {
        "status": "done",
        "exit_code": exit_code,
        "output": merged_output if merged_output else "(命令已被强制终止)"
    })
    _running_processes.pop(command_id, None)

    log.info(f"命令已强制终止: command_id={command_id}, exit_code={exit_code}")

    return {
        "status": "done",
        "exit_code": exit_code,
        "output": merged_output if merged_output else "(命令已被强制终止)"
    }


def _cleanup_all_processes():
    """清理所有正在运行的后台进程并清空缓存（退出时调用）。"""
    for cid, proc_info in list(_running_processes.items()):
        try:
            process = proc_info['process']
            _close_transports(proc_info)
            if process.returncode is None:
                process.kill()
        except Exception:
            pass
    _running_processes.clear()
    # 清空所有缓存
    get_command_cache_manager().clear_all()


def _signal_handler(signum, frame):
    """处理退出信号：请求解释器正常退出。

    进程与缓存清理由 atexit 注册的 _cleanup_all_processes 兜底，
    此处不做重复清理。防重入 + 解释器退出阶段检查，避免在
    atexit 回调执行期间二次抛出 SystemExit，产生
    "Exception ignored in atexit callback" 噪音。
    """
    global _shutdown_started
    if _shutdown_started or sys.is_finalizing():
        return
    _shutdown_started = True
    log.info(f"收到退出信号 {signum}，开始退出")
    raise SystemExit(0)


async def _start_process(script: str, work_path: Path, command_id: str = ""):
    """启动 PowerShell 进程执行脚本。

    Args:
        script: 要执行的 PowerShell 脚本
        work_path: 进程工作目录
        command_id: 命令标识，用于日志

    Returns:
        asyncio 子进程对象
    """
    wrapper = (
        f'[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n'
        f'$ErrorActionPreference = "Continue"\n'
        f'{script}\n'
    )
    encoded = base64.b64encode(wrapper.encode('utf-16-le')).decode('ascii')

    log.info(f"启动进程: command_id={command_id}, script_len={len(script)}")

    return await asyncio.create_subprocess_exec(
        'powershell', '-NoProfile', '-EncodedCommand', encoded,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(work_path)
    )
