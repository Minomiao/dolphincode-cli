import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from modules.logger import get_logger
from modules.bootstrap import constants

log = get_logger("Dolphin.command_cache")


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
            persist_path = Path(app_paths.DATE_DIR) / constants.COMMAND_CACHE_PERSIST_DIR
            persist_path.mkdir(parents=True, exist_ok=True)
            return persist_path
        except Exception as e:
            log.warning(f"无法创建持久化目录: {e}")
            # Fallback: 使用当前工作目录下的 date/command_cache
            return Path("date") / constants.COMMAND_CACHE_PERSIST_DIR

    def _get_persist_file(self, command_id: str) -> Path:
        """获取命令的持久化文件路径"""
        return self._persist_dir / f"{command_id}.json"

    def add(self, command_id: str, data: Dict[str, Any]) -> None:
        """添加缓存条目（带 TTL）"""
        cached_at = time.time()
        cache_entry = {
            **data,
            "cached_at": cached_at,
            "expires_at": cached_at + constants.COMMAND_CACHE_TTL_SECONDS
        }

        # 检查内存缓存大小，超过限制时清理最旧的
        if len(self._memory_cache) >= constants.MAX_COMMAND_CACHE_SIZE:
            self._cleanup_oldest_memory_cache()

        self._memory_cache[command_id] = cache_entry
        log.debug(f"缓存已添加: {command_id}, TTL={constants.COMMAND_CACHE_TTL_SECONDS}秒")

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
            entry['expires_at'] = time.time() + constants.COMMAND_CACHE_PERSIST_TTL_SECONDS
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
            "ttl_seconds": constants.COMMAND_CACHE_TTL_SECONDS,
            "persist_ttl_seconds": constants.COMMAND_CACHE_PERSIST_TTL_SECONDS,
            "max_memory_cache_size": constants.MAX_COMMAND_CACHE_SIZE
        }


# 全局缓存管理器实例（惰性：首次使用时才创建，避免 import 时产生磁盘写入副作用）
_cache_manager: Optional[CommandCacheManager] = None


def get_command_cache_manager() -> CommandCacheManager:
    """获取全局命令缓存管理器单例（首次调用时创建）。"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CommandCacheManager()
    return _cache_manager
