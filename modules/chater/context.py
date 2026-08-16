"""
上下文管理器: 负责构建、压缩和优化发送给模型的消息列表。

职责:
- 将 system prompt + 对话历史拼接为 API 所需的 messages 格式
- 将动态上下文追加到末尾 user message 以保持前缀稳定，提高缓存命中率
- 预留上下文压缩、token 预算管理、滑动窗口等扩展点
"""

import time

from modules.logger import get_logger
from modules.bootstrap import constants

log = get_logger("Dolphin.context")

# 上下文窗口告警阈值
_WARN_THRESHOLD = constants.WARN_THRESHOLD
_HIGH_THRESHOLD = constants.HIGH_THRESHOLD
_CRITICAL_THRESHOLD = constants.CRITICAL_THRESHOLD



class ContextManager:
    """管理发送给 API 的上下文消息列表。"""

    def __init__(self, get_system_prompt, get_context_prompt=None):
        self._get_system_prompt = get_system_prompt
        self._get_context_prompt = get_context_prompt
        self._cumulative_prompt_tokens = 0
        self._cumulative_completion_tokens = 0
        # 上一轮的 prompt_tokens（用于计算本轮增量）
        self._previous_prompt_tokens = 0
        # DeepSeek 硬盘缓存命中统计
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0
        self._turn_count = 0

    def prepare_messages(self, messages: list) -> list:
        """构建最终发送给 API 的完整消息列表。

        动态上下文（工作目录、目录结构、努力程度）通过独立 _context 字段存储，
        发送时从 content + _context 拼接，写回时只写 _context 不污染 content。
        末尾 user message 额外追加本轮 context。
        保持前缀稳定以提高 DeepSeek 缓存命中率。

        Args:
            messages: 当前的对话历史列表 (self.messages)
        """
        start = time.perf_counter()
        system_message = {"role": "system", "content": self._get_system_prompt()}

        # 确保 system 在最前面且不重复
        if messages and messages[0].get("role") == "system":
            source = messages[1:]
        else:
            source = messages

        # 构建发送用列表：对有 _context 的 user 消息还原完整 content
        result = [system_message]
        for msg in source:
            if msg.get("role") == "user" and msg.get("_context"):
                msg = dict(msg)
                msg["content"] = msg["content"] + "\n\n" + msg.pop("_context")
            result.append(msg)

        # 每轮注入动态上下文：追加到最后一条 user message 末尾
        # 同步写回 _context 字段，保持 content 为原始用户输入
        if self._get_context_prompt:
            context = self._get_context_prompt()
            if context:
                for i in range(len(result) - 1, -1, -1):
                    if result[i].get("role") == "user":
                        result[i] = dict(result[i])
                        result[i]["content"] = result[i]["content"] + "\n\n" + context
                        # 写回 _context，content 保持不变
                        msg_idx = i - 1  # result[0] 是 system_message，result[1:] 对应 source(=messages[1:] or messages)
                        if (messages and messages[0].get("role") == "system"):
                            msg_idx = i  # result[i] 直接对应 messages[i]
                        if 0 <= msg_idx < len(messages):
                            messages[msg_idx] = dict(messages[msg_idx])
                            messages[msg_idx]["_context"] = context
                        break
                else:
                    result.append({"role": "user", "content": context})
                    messages.append({"role": "user", "content": context})

        elapsed = time.perf_counter() - start
        log.debug(f"准备消息完成: {len(result)} 条, 耗时={elapsed:.3f}s")
        return result

    def check_context_usage(self, messages: list, context_window: int) -> dict | None:
        """检查当前上下文用量，在接近窗口上限时返回告警信息。

        Args:
            messages: 当前对话历史
            context_window: 模型的上下文窗口大小 (由调用方从 config 传入)

        Returns:
            None 表示使用率正常；dict 包含 usage_ratio / context_window / estimated_tokens / level
            以及 cache_hit_tokens / cache_miss_tokens / cache_hit_ratio 等缓存统计
        """
        # 优先使用 API 返回的精确值
        if self._cumulative_prompt_tokens > 0:
            # 累计 prompt_tokens + 最后一轮 completion_tokens
            estimated = self._cumulative_prompt_tokens + self._cumulative_completion_tokens
            source = "api"
        else:
            estimated = self._estimate_tokens(messages)
            source = "estimated"

        ratio = estimated / context_window

        level = None
        if ratio >= _CRITICAL_THRESHOLD:
            level = "critical"
        elif ratio >= _HIGH_THRESHOLD:
            level = "high"
        elif ratio >= _WARN_THRESHOLD:
            level = "warn"

        if level is not None:
            log.info(
                f"上下文用量告警: {ratio:.1%} ({estimated}/{context_window} tokens), level={level}, source={source}"
            )

        # 计算本轮缓存命中率
        cache_total = self._cache_hit_tokens + self._cache_miss_tokens
        cache_hit_ratio = self._cache_hit_tokens / cache_total if cache_total > 0 else 0

        return {
            "usage_ratio": ratio,
            "context_window": context_window,
            "estimated_tokens": estimated,
            "level": level,  # None 表示无告警
            "source": source,
            "prompt_tokens": self._cumulative_prompt_tokens,
            "completion_tokens": self._cumulative_completion_tokens,
            # 本轮增量
            "turn_prompt_tokens": max(0, self._cumulative_prompt_tokens - self._previous_prompt_tokens),
            "turn_completion_tokens": self._cumulative_completion_tokens,
            # 缓存命中统计
            "cache_hit_tokens": self._cache_hit_tokens,
            "cache_miss_tokens": self._cache_miss_tokens,
            "cache_hit_ratio": cache_hit_ratio,
            "turn_count": self._turn_count,
        }

    def update_usage_from_api(self, usage) -> None:
        """从 API 响应更新 token 用量（精确值）。

        Args:
            usage: OpenAI API 返回的 usage 对象，包含 prompt_tokens, completion_tokens,
                   DeepSeek 的 prompt_cache_hit_tokens / prompt_cache_miss_tokens 等
        """
        if usage is None:
            return

        self._turn_count += 1

        # 更新累计值：prompt_tokens 代表当前完整上下文，completion_tokens 是本轮输出
        if hasattr(usage, 'prompt_tokens') and usage.prompt_tokens:
            self._previous_prompt_tokens = self._cumulative_prompt_tokens
            self._cumulative_prompt_tokens = usage.prompt_tokens
        if hasattr(usage, 'completion_tokens') and usage.completion_tokens:
            self._cumulative_completion_tokens = usage.completion_tokens

        # 捕获 DeepSeek 硬盘缓存命中统计
        # prompt_cache_hit_tokens: 缓存命中的 token 数
        # prompt_cache_miss_tokens: 缓存未命中的 token 数（需重新计算）
        hit = getattr(usage, 'prompt_cache_hit_tokens', None)
        miss = getattr(usage, 'prompt_cache_miss_tokens', None)
        if hit is not None:
            self._cache_hit_tokens = hit
        if miss is not None:
            self._cache_miss_tokens = miss

        log.debug(
            f"Token 用量已更新: prompt={self._cumulative_prompt_tokens}, "
            f"completion={self._cumulative_completion_tokens}, "
            f"cache_hit={self._cache_hit_tokens}, cache_miss={self._cache_miss_tokens}"
        )

    def reset_usage(self) -> None:
        """重置 token 用量统计（在清空历史时调用）。"""
        self._cumulative_prompt_tokens = 0
        self._cumulative_completion_tokens = 0
        self._previous_prompt_tokens = 0
        self._cache_hit_tokens = 0
        self._cache_miss_tokens = 0
        self._turn_count = 0

    def _estimate_tokens(self, messages: list) -> int:
        """估算消息列表的 token 数量 (近似算法)。

        中文约 1 字 = 1.5 token，英文约 1 词 ≈ 1.3 token。
        这里采用粗略平均: 字符数 / 3 作为 token 数估算。
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                # 粗略估算: 每 3 个字符 ≈ 1 token
                total += max(1, len(content) // 3)
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "")
                    name = fn.get("name", "")
                    total += max(1, len(args) // 3)
                    total += max(1, len(name) // 3)
            if msg.get("reasoning_content"):
                rc = msg["reasoning_content"]
                if isinstance(rc, str):
                    total += max(1, len(rc) // 3)
        return total
