import re
import requests
import os
import warnings
import logging
import ipaddress
from urllib.parse import urlparse

from typing import Dict, Any, List, Set

# 抑制 jieba 的警告与初始化日志（jieba 初始化日志通过 logging 输出，无需劫持 stdout）
warnings.filterwarnings("ignore", category=UserWarning, module="jieba")

import jieba
jieba.setLogLevel(logging.CRITICAL)


# ===== 停用词表加载 =====
_STOP_WORDS_FILE = os.path.join(os.path.dirname(__file__), "stop_words.txt")
_USER_DICT_FILE = os.path.join(os.path.dirname(__file__), "user_dict.txt")
_STOP_WORDS: Set[str] = set()


def _load_stop_words() -> Set[str]:
    """从 stop_words.txt 加载停用词表。"""
    global _STOP_WORDS
    if _STOP_WORDS:
        return _STOP_WORDS

    try:
        if os.path.isfile(_STOP_WORDS_FILE):
            with open(_STOP_WORDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过空行和注释
                    if line and not line.startswith('#'):
                        _STOP_WORDS.add(line.lower())
    except Exception:
        pass

    # 确保至少有基本停用词（文件不存在时的兜底）
    if not _STOP_WORDS:
        _STOP_WORDS = {
            "的", "是", "了", "在", "和", "与", "或", "不", "有", "我", "他", "她", "它",
            "这", "那", "都", "也", "就", "还", "要", "会", "能", "对", "把", "被", "让",
            "从", "到", "很", "更", "最", "已", "着", "呢", "吗", "吧", "啊", "哦", "嗯",
            "如何", "怎么", "什么", "为什么", "哪个", "哪些", "哪里", "那里", "这里",
            "可以", "能够", "应该", "需要", "想要", "希望", "想", "请", "给", "把",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "shall",
            "should", "can", "could", "may", "might", "must", "in", "on", "at",
            "to", "for", "of", "with", "by", "from", "as", "or", "and", "not",
            "but", "if", "so", "no", "up", "out", "all", "any", "both", "each",
            "few", "more", "most", "other", "some", "such", "only", "own", "same",
            "than", "too", "very", "just", "about", "into", "over", "also",
            "how", "what", "which", "when", "where", "who", "why", "vs", "vs.",
        }

    return _STOP_WORDS


def _init_jieba():
    """初始化 jieba 分词器。"""
    # 加载自定义词典（如果存在）
    if os.path.isfile(_USER_DICT_FILE):
        jieba.load_userdict(_USER_DICT_FILE)


# 启动时初始化
_load_stop_words()
_init_jieba()


skill_info = {
    "name": "web_search",
    "description": "网络搜索技能，可以搜索网络信息",
    "functions": {
        "search": {
            "description": "搜索网络信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "num_results": {"type": "integer", "description": "返回结果数量，默认为15"}
                },
                "required": ["query"]
            }
        },
        "fetch": {
            "description": "解析指定网址的网页内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "要解析的网页URL"}
                },
                "required": ["url"]
            }
        }
    }
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# ---- 关键字匹配过滤（主方案）----
_KEYWORD_MIN_LEN = 2


def _extract_keywords(query: str) -> List[str]:
    """从查询中提取有意义的关键字。

    使用 jieba 分词，过滤停用词和短词。
    """
    cleaned = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', query).strip()

    keywords = []
    tokens = cleaned.split()

    for token in tokens:
        token = token.lower().strip()
        if not token:
            continue

        # 英文 token（无中文字符）
        if token.isalpha() and not any('\u4e00' <= c <= '\u9fff' for c in token):
            if token not in _STOP_WORDS and len(token) >= _KEYWORD_MIN_LEN:
                keywords.append(token)
            continue

        # 中文 token：使用 jieba 分词
        words = list(jieba.cut(token))
        for word in words:
            word = word.strip()
            if word and word not in _STOP_WORDS and len(word) >= _KEYWORD_MIN_LEN:
                keywords.append(word)

    return keywords


def _build_user_output(query: str, results: list) -> list:
    return [
        {"text": f'"{query}"'},
        {"text": f"- {len(results)} results", "style": "gray"}
    ]


# ---- 相关性过滤 ----

def _filter_relevant(query: str, results: List[Dict]) -> tuple:
    """对搜索结果做关键字匹配过滤。

    Returns:
        (filtered_results, irrelevant_results): 相关结果列表 + 无关结果列表
    """
    if not results:
        return [], []

    keywords = _extract_keywords(query)
    if not keywords:
        return results, []

    filtered = []
    irrelevant = []
    for r in results:
        text = (r.get("title", "") + " " + r.get("content", "")).lower()
        if any(kw in text for kw in keywords):
            filtered.append(r)
        else:
            irrelevant.append(r)

    # 如果全部匹配或全部不匹配，直接返回
    return filtered, irrelevant


# ---- 搜索入口 ----

def _parse_bing_results(html: str, max_count: int) -> List[Dict]:
    """从 Bing 搜索 HTML 中解析结果。

    Args:
        html: Bing 搜索返回的 HTML
        max_count: 最大解析数量

    Returns:
        解析后的结果列表
    """
    results = []
    blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)

    for block in blocks:
        if len(results) >= max_count:
            break

        # 提取 h2 中的链接和标题
        h2_match = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
        if not h2_match:
            continue

        h2_content = h2_match.group(1)
        link_match = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', h2_content, re.DOTALL)
        if not link_match:
            continue

        url_val = link_match.group(1)
        title = re.sub(r'<[^>]+>', '', link_match.group(2)).strip()
        if not title:
            continue

        # 提取摘要
        caption_match = re.search(r'<div class="b_caption"[^>]*>(.*?)</div>', block, re.DOTALL)
        snippet = ""
        if caption_match:
            p_match = re.search(r'<p[^>]*>(.*?)</p>', caption_match.group(1), re.DOTALL)
            if p_match:
                snippet = re.sub(r'<[^>]+>', '', p_match.group(1)).strip()

        results.append({
            "title": title,
            "content": snippet,
            "url": url_val
        })

    return results


def search(context, query: str, num_results: int = None) -> Dict[str, Any]:
    """搜索网络信息，相关结果占 1/3，其余保留原始结果。

    Args:
        query: 搜索关键词
        num_results: 目标结果数量，默认为 WEB_SEARCH_DEFAULT_RESULTS

    Returns:
        搜索结果字典

    策略：
        1. 搜索 3 倍目标数量的结果
        2. 关键字过滤得到相关结果（目标占 1/3）
        3. 合并返回：相关结果优先 + 部分原始结果补齐
    """
    if num_results is None:
        num_results = context.constants.WEB_SEARCH_DEFAULT_RESULTS

    try:
        # 搜索 3 倍数量以获得足够的相关结果（期望相关结果占 1/3）
        fetch_count = num_results * 3

        url = "https://www.bing.com/search"
        params = {"q": query, "count": fetch_count}
        resp = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 解析结果
        raw_results = _parse_bing_results(html, fetch_count)

        if not raw_results:
            return {
                "query": query,
                "results": [],
                "user_output": {"label": "Search", "parts": [{"text": f'"{query}"'}, {"text": "- 0 results", "style": "gray"}]}
            }

        # 关键字过滤：分离相关结果和无关结果
        filtered_results, irrelevant_results = _filter_relevant(query, raw_results)

        # 组装最终结果：相关结果优先，不足时用无关结果补齐
        final_results = []

        # 相关结果放前面（目标占 1/3）
        relevant_count = min(len(filtered_results), num_results)
        final_results.extend(filtered_results[:relevant_count])

        # 如果相关结果不足，用无关结果补齐到目标数量
        if len(final_results) < num_results and irrelevant_results:
            remaining = num_results - len(final_results)
            final_results.extend(irrelevant_results[:remaining])

        return {
            "query": query,
            "results": final_results,
            "user_output": {"label": "Search", "parts": _build_user_output(query, final_results)}
        }

    except Exception as e:
        return {
            "error": str(e),
            "query": query,
            "results": [],
            "user_output": {"label": "Search", "parts": [{"text": f'"{query}"'}, {"text": "- Error", "style": "gray"}]}
        }


# ---- 网页解析 ----

def _is_safe_url(url: str) -> bool:
    """校验 URL 是否允许抓取，防止 SSRF（拒绝私网/环回/链路本地地址）。"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return True  # 域名不做解析校验
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved)


def fetch(context, url: str) -> Dict[str, Any]:
    """解析指定网址的网页内容。"""
    try:
        if not _is_safe_url(url):
            return {
                "error": f"不允许抓取的地址: {url}",
                "url": url,
                "content": "",
                "user_output": {"label": "Fetch", "parts": [{"text": f'"{url}"'}, {"text": "- Error", "style": "gray"}]}
            }
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 提取标题
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""

        # 移除脚本和样式
        cleaned = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # 移除所有标签
        text = re.sub(r'<[^>]+>', ' ', cleaned)
        # 清理空白
        text = re.sub(r'\s+', ' ', text).strip()

        # 截断过长的内容
        if len(text) > context.constants.MAX_WEB_CONTENT_LENGTH:
            text = text[:context.constants.MAX_WEB_CONTENT_LENGTH] + "..."

        return {
            "url": url,
            "title": title,
            "content": text,
            "user_output": {"label": "Fetch", "parts": [{"text": f'"{title or url}"'}, {"text": "- OK", "style": "gray"}]}
        }

    except Exception as e:
        return {
            "error": str(e),
            "url": url,
            "content": "",
            "user_output": {"label": "Fetch", "parts": [{"text": f'"{url}"'}, {"text": "- Error", "style": "gray"}]}
        }
