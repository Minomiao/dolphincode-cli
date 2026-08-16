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

log = get_logger("Dolphin.powershell_manager")

MAX_SCRIPT_LENGTH = constants.MAX_SCRIPT_LENGTH
MAX_OUTPUT_LENGTH = constants.MAX_OUTPUT_LENGTH
MAX_OUTPUT_LINES = constants.MAX_OUTPUT_LINES
DEFAULT_TIMEOUT = constants.DEFAULT_TIMEOUT
DEFAULT_WAIT_TIME = constants.DEFAULT_WAIT_TIME

# 缓存配置
COMMAND_CACHE_TTL = constants.COMMAND_CACHE_TTL_SECONDS
COMMAND_CACHE_PERSIST_DIR = constants.COMMAND_CACHE_PERSIST_DIR
COMMAND_CACHE_PERSIST_TTL = constants.COMMAND_CACHE_PERSIST_TTL_SECONDS
MAX_COMMAND_CACHE_SIZE = constants.MAX_COMMAND_CACHE_SIZE

_running_processes: Dict[str, Dict[str, Any]] = {}
_process_counter = 0
# 后台自动清理任务集合：保存引用避免任务被 GC 时产生 "Task was destroyed" 警告
_bg_cleanup_tasks: set = set()
# 退出信号是否已处理，防止重复触发
_shutdown_started = False

# 后台进程最长存活时间（秒），超时自动清理防止泄漏
MAX_BACKGROUND_LIFETIME = constants.MAX_BACKGROUND_LIFETIME


class CommandCacheManager:
    """命令缓存管理器：支持 TTL、自动销毁、持久化"""
    
    def __init__(self):
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._persist_dir = self._get_persist_dir()
        log.info("CommandCacheManager 初始化完成")
    
    def _get_persist_dir(self) -> Path:
        """获取持久化缓存目录（位于 date 目录下，受 DPC 保护）"""
        try:
            from modules import bootstrap as app_paths
            # 使用 DATE_DIR 而不是 PROJECT_ROOT
            persist_path = Path(app_paths.DATE_DIR) / COMMAND_CACHE_PERSIST_DIR
            persist_path.mkdir(parents=True, exist_ok=True)
            return persist_path
        except Exception as e:
            log.warning(f"无法创建持久化目录: {e}")
            # Fallback: 使用当前工作目录下的 date/command_cache
            return Path("date") / COMMAND_CACHE_PERSIST_DIR
    
    def _get_persist_file(self, command_id: str) -> Path:
        """获取命令的持久化文件路径"""
        return self._persist_dir / f"{command_id}.json"
    
    def add(self, command_id: str, data: Dict[str, Any]) -> None:
        """添加缓存条目（带 TTL）"""
        cached_at = time.time()
        cache_entry = {
            **data,
            "cached_at": cached_at,
            "expires_at": cached_at + COMMAND_CACHE_TTL
        }
        
        # 检查内存缓存大小，超过限制时清理最旧的
        if len(self._memory_cache) >= MAX_COMMAND_CACHE_SIZE:
            self._cleanup_oldest_memory_cache()
        
        self._memory_cache[command_id] = cache_entry
        log.debug(f"缓存已添加: {command_id}, TTL={COMMAND_CACHE_TTL}秒")
    
    def get(self, command_id: str) -> Optional[Dict[str, Any]]:
        """获取缓存（检查 TTL）"""
        # 1. 先检查内存缓存
        if command_id in self._memory_cache:
            entry = self._memory_cache[command_id]
            if self._is_expired(entry):
                # 已过期，从内存删除（不转储到持久化，因为已有充足时间读取）
                del self._memory_cache[command_id]
                log.debug(f"内存缓存已过期: {command_id}")
                return None
            # 未过期，返回副本并标记为已读取
            result = {k: v for k, v in entry.items() if k not in ['cached_at', 'expires_at']}
            # AI 读取后立即销毁（按用户需求）
            del self._memory_cache[command_id]
            log.debug(f"AI 读取缓存后销毁: {command_id}")
            return result
        
        # 2. 检查持久化缓存
        persist_file = self._get_persist_file(command_id)
        if persist_file.exists():
            try:
                with open(persist_file, 'r', encoding='utf-8') as f:
                    entry = json.load(f)
                
                if self._is_expired(entry):
                    # 持久化缓存也已过期，删除文件
                    persist_file.unlink()
                    log.debug(f"持久化缓存已过期并删除: {command_id}")
                    return None
                
                # 读取后销毁持久化文件
                persist_file.unlink()
                log.debug(f"AI 读取持久化缓存后销毁: {command_id}")
                
                # 返回结果（移除元数据）
                return {k: v for k, v in entry.items() if k not in ['cached_at', 'expires_at']}
            except Exception as e:
                log.warning(f"读取持久化缓存失败: {command_id}, {e}")
                return None
        
        return None
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """检查缓存是否已过期"""
        expires_at = entry.get('expires_at', 0)
        return time.time() > expires_at
    
    def _cleanup_oldest_memory_cache(self) -> int:
        """清理最旧的内存缓存条目"""
        if not self._memory_cache:
            return 0
        
        # 找出最旧的条目
        oldest_key = min(
            self._memory_cache.keys(),
            key=lambda k: self._memory_cache[k].get('cached_at', 0)
        )
        oldest_entry = self._memory_cache[oldest_key]
        
        # 转储到持久化（而不是直接删除）
        self._persist_entry(oldest_key, oldest_entry)
        
        # 从内存删除
        del self._memory_cache[oldest_key]
        log.debug(f"清理最旧内存缓存并转储: {oldest_key}")
        return 1
    
    def _persist_entry(self, command_id: str, entry: Dict[str, Any]) -> None:
        """将过期条目转储到持久化存储"""
        try:
            # 更新过期时间为持久化 TTL
            entry['expires_at'] = time.time() + COMMAND_CACHE_PERSIST_TTL
            persist_file = self._get_persist_file(command_id)
            
            with open(persist_file, 'w', encoding='utf-8') as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
            
            log.debug(f"缓存已转储到持久化: {command_id}")
        except Exception as e:
            log.warning(f"持久化缓存失败: {command_id}, {e}")
    
    def cleanup_expired_persistent(self, force_all: bool = False) -> int:
        """清理过期的持久化缓存文件
        
        Args:
            force_all: 是否强制删除所有文件（用于启动时清理）
        """
        cleaned = 0
        try:
            for file_path in self._persist_dir.glob("*.json"):
                try:
                    # 如果 force_all=True，直接删除所有文件
                    if force_all:
                        file_path.unlink()
                        cleaned += 1
                        continue
                    
                    # 否则检查 TTL
                    with open(file_path, 'r', encoding='utf-8') as f:
                        entry = json.load(f)
                    
                    if self._is_expired(entry):
                        file_path.unlink()
                        cleaned += 1
                except Exception:
                    # 损坏的文件也删除
                    try:
                        file_path.unlink()
                        cleaned += 1
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"清理持久化缓存失败: {e}")
        
        if cleaned > 0:
            mode = "所有" if force_all else "过期"
            log.info(f"启动时清理了 {cleaned} 个{mode}持久化缓存")
        return cleaned
    
    def clear_all(self) -> None:
        """清空所有缓存"""
        self._memory_cache.clear()
        
        # 清理持久化目录
        try:
            for file_path in self._persist_dir.glob("*.json"):
                file_path.unlink()
        except Exception as e:
            log.warning(f"清理持久化缓存失败: {e}")
        
        log.info("所有命令缓存已清空")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            "memory_cache_count": len(self._memory_cache),
            "persist_cache_count": len(list(self._persist_dir.glob("*.json"))),
            "ttl_seconds": COMMAND_CACHE_TTL,
            "persist_ttl_seconds": COMMAND_CACHE_PERSIST_TTL,
            "max_memory_cache_size": MAX_COMMAND_CACHE_SIZE
        }


# 全局缓存管理器实例
_cache_manager = CommandCacheManager()


def init():
    """显式初始化 PowerShell 管理模块：清理持久化缓存、注册退出清理与信号处理。

    由 main.py 在启动时调用一次，避免模块导入时产生副作用。
    """
    _cache_manager.cleanup_expired_persistent(force_all=True)
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


async def _read_stream(stream: asyncio.StreamReader, buffer: list, max_chars: int = MAX_OUTPUT_LENGTH):
    """读取流内容到缓冲区，最多读取 max_chars 个字符。"""
    total = 0
    while total < max_chars:
        try:
            line = await stream.readline()
        except Exception:
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


async def _auto_kill_background(command_id: str, delay: int = MAX_BACKGROUND_LIFETIME) -> None:
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


async def execute_script(script: str, timeout: int = DEFAULT_TIMEOUT, wait_time: int = DEFAULT_WAIT_TIME) -> Dict[str, Any]:
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
            if len(stdout) > MAX_OUTPUT_LENGTH:
                stdout = stdout[:MAX_OUTPUT_LENGTH] + f"\n... (输出已截断)"

            _close_transports(proc_info)
            # 使用新的缓存管理器（带 TTL）
            _cache_manager.add(command_id, {
                "status": "done",
                "exit_code": process.returncode,
                "output": stdout
            })
            _running_processes.pop(command_id, None)

            elapsed = time.time() - exec_start
            log.info(f"命令完成: command_id={command_id}, returncode={process.returncode}, 耗时={elapsed:.3f}s")

            return {
                "success": True,
                "return_code": process.returncode,
                "output": stdout,
                "completed": True,
                "command_id": command_id,
                "message": f"脚本执行完成，返回码: {process.returncode}"
            }

        except asyncio.TimeoutError:
            await asyncio.sleep(0.1)
            stdout = ''.join(stdout_buffer)

            # 注册后台超时自动清理：后台存活不超过 timeout（至少 wait_time），防止进程永久泄漏
            task = asyncio.create_task(_auto_kill_background(command_id, delay=max(timeout, wait_time)))
            # 保存引用，避免任务被 GC 时产生 "Task was destroyed but it is pending!" 警告
            _bg_cleanup_tasks.add(task)
            task.add_done_callback(_bg_cleanup_tasks.discard)

            elapsed = time.time() - exec_start
            log.info(f"命令仍在运行: command_id={command_id}, stdout={len(stdout)}字, 已耗时={elapsed:.3f}s")

            return {
                "success": True,
                "output": stdout if stdout else "(命令正在运行中...)",
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
        _cache_manager.add(command_id, {
            "status": "done",
            "exit_code": None,
            "output": ""
        })
        return {"error": f"命令执行失败: {str(e)}", "command_id": command_id, "output": ""}


async def check_script(command_id: str, wait_time: int = DEFAULT_WAIT_TIME) -> Dict[str, Any]:
    # 先检查缓存（使用新的缓存管理器，支持 TTL）
    cached_result = _cache_manager.get(command_id)
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
        return_code = process.returncode

        _close_transports(proc_info)
        # 使用新的缓存管理器
        _cache_manager.add(command_id, {
            "status": "done",
            "exit_code": return_code,
            "output": stdout
        })
        _running_processes.pop(command_id, None)

        elapsed = time.time() - check_start
        log.info(f"命令完成: command_id={command_id}, returncode={return_code}, 耗时={elapsed:.3f}s")

        lines = stdout.split('\n')
        if len(lines) > MAX_OUTPUT_LINES:
            stdout = '\n'.join(lines[-MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

        return {
            "status": "done",
            "exit_code": return_code,
            "output": stdout
        }

    except asyncio.TimeoutError:
        await asyncio.sleep(0.1)
        stdout = ''.join(proc_info['stdout_buffer'])

        lines = stdout.split('\n')
        if len(lines) > MAX_OUTPUT_LINES:
            stdout = '\n'.join(lines[-MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

        elapsed = time.time() - check_start
        log.info(f"命令仍在运行: command_id={command_id}, 已耗时={elapsed:.3f}s")

        return {
            "status": "running",
            "output": stdout if stdout else "(命令正在运行中...)"
        }


def kill_command(command_id: str) -> Dict[str, Any]:
    """强制终止指定命令的后台进程并返回其输出。"""
    # 先检查缓存
    cached_result = _cache_manager.get(command_id)
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
    exit_code = process.returncode

    lines = stdout.split('\n')
    if len(lines) > MAX_OUTPUT_LINES:
        stdout = '\n'.join(lines[-MAX_OUTPUT_LINES:]) + f"\n... (输出已截断，共 {len(lines)} 行)"

    # 使用新的缓存管理器
    _cache_manager.add(command_id, {
        "status": "done",
        "exit_code": exit_code,
        "output": stdout if stdout else "(命令已被强制终止)"
    })
    _running_processes.pop(command_id, None)

    log.info(f"命令已强制终止: command_id={command_id}, exit_code={exit_code}")

    return {
        "status": "done",
        "exit_code": exit_code,
        "output": stdout if stdout else "(命令已被强制终止)"
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
    _cache_manager.clear_all()


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
