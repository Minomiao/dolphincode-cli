"""多模态视觉支持模块。

职责:
- 从用户输入解析 @ 前缀图片引用（引号定界 + 存在性校验，防误判）
- 查询模型视觉能力声明（models.json capabilities）与图片传输方式
- 构建 OpenAI 兼容的 content parts（file_id 引用或 base64 内联）
- read_image 工具的图片文件校验入口
"""

import base64
import mimetypes
import os
import re

from modules.bootstrap import constants
from modules.logger import get_logger
from modules.main_server import config

log = get_logger("Dolphin.vision")

# @ 引用正则：@"带引号路径"（可含空格）或 @无空白路径
_AT_TOKEN_RE = re.compile(r'@(?:"([^"]+)"|([^\s]+))')

# 单图大小上限：与 DeepSeek Files API 对齐
IMAGE_MAX_BYTES = 64 * 1024 * 1024

# file_id 缓存：{(绝对路径, mtime): file_id}，避免同一图片跨轮重复上传
_file_id_cache = {}


def guess_media_type(path: str) -> str:
    """根据扩展名推断图片 MIME 类型。"""
    media_type, _ = mimetypes.guess_type(path)
    return media_type or "image/png"


def _is_valid_image(path: str) -> bool:
    """路径为存在的图片文件时返回 True。"""
    ext = os.path.splitext(path)[1].lower()
    if ext not in constants.IMAGE_EXTENSIONS:
        return False
    return os.path.isfile(path)


def extract_images(text: str) -> tuple:
    """解析文本中的 @ 图片引用。

    规则：
    - @"路径"（引号定界，可含空格）或 @路径（到空白为止）
    - 路径必须真实存在且为图片扩展名，否则原样保留（宁可漏识别不误识别）

    Args:
        text: 原始用户输入

    Returns:
        (清理后的文本, 图片列表)；图片列表元素为 {"path": 绝对路径, "media_type": MIME}
    """
    images = []
    remove_spans = []
    for match in _AT_TOKEN_RE.finditer(text):
        raw_path = match.group(1) or match.group(2)
        path = os.path.realpath(raw_path)
        if not _is_valid_image(path):
            continue
        images.append({"path": path, "media_type": guess_media_type(path)})
        remove_spans.append(match.span())

    if not images:
        return text, []

    # 从文本中剔除已识别的引用片段，合并多余空白
    segments = []
    last = 0
    for start, end in remove_spans:
        segments.append(text[last:start])
        last = end
    segments.append(text[last:])
    clean = re.sub(r"[ \t]{2,}", " ", "".join(segments)).strip()

    log.info(f"识别到 {len(images)} 张图片引用: {[img['path'] for img in images]}")
    return clean, images


def _get_model_meta(model_name: str) -> dict | None:
    """查询模型元数据（来自 models.json 统一清单）。"""
    return config.get_model_metadata(model_name or "")


def is_vision_capable(model_name: str) -> bool:
    """模型声明了视觉能力时返回 True。"""
    meta = _get_model_meta(model_name)
    return constants.MODEL_CAPABILITY_VISION in (meta or {}).get("capabilities", [])


def use_files_transport(model_name: str) -> bool:
    """模型配置为 file 传输（Files API 引用）时返回 True，否则 base64 内联。"""
    meta = _get_model_meta(model_name)
    return (meta or {}).get("vision_transport") == "file"


def ensure_file_id(client, path: str) -> str:
    """上传图片到 Files API 并返回 file_id，带 (路径, mtime) 缓存。

    Args:
        client: OpenAI 客户端（与当前模型同一 base_url）
        path: 图片绝对路径

    Raises:
        上传失败时抛出原始异常，由调用方决定回退策略
    """
    abspath = os.path.realpath(path)
    key = (abspath, os.path.getmtime(abspath))
    cached = _file_id_cache.get(key)
    if cached:
        return cached
    with open(abspath, "rb") as f:
        created = client.files.create(file=(os.path.basename(abspath), f), purpose="user_data")
    _file_id_cache[key] = created.id
    log.info(f"图片已上传: {abspath} -> {created.id}")
    return created.id


def _base64_part(path: str) -> dict:
    """构建 base64 内联图片块。"""
    abspath = os.path.realpath(path)
    with open(abspath, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    url = f"data:{guess_media_type(abspath)};base64,{data}"
    return {"type": "image_url", "image_url": {"url": url}}


def build_image_parts(images: list, client, model_name: str) -> list:
    """把内部图片列表转换为 OpenAI 兼容的 content parts。

    优先使用模型配置的传输方式；file 上传失败时回退 base64。
    """
    parts = []
    for img in images:
        if use_files_transport(model_name):
            try:
                parts.append({"type": "file", "file_id": ensure_file_id(client, img["path"])})
                continue
            except Exception as e:
                log.warning(f"file_id 上传失败，回退 base64: {img['path']}, 错误: {e}")
        parts.append(_base64_part(img["path"]))
    return parts


def read_image_file(path: str) -> dict:
    """校验图片文件（read_image 工具入口）。

    Returns:
        成功: {"success": True, "path", "media_type", "size"}
        失败: {"error", "suggestion"}
    """
    if not path or not str(path).strip():
        return {"error": "缺少图片路径参数", "suggestion": "请提供图片文件的路径"}
    abspath = os.path.realpath(str(path).strip())
    if not os.path.isfile(abspath):
        return {"error": f"文件不存在: {abspath}", "suggestion": "请确认路径是否正确"}
    ext = os.path.splitext(abspath)[1].lower()
    if ext not in constants.IMAGE_EXTENSIONS:
        return {
            "error": f"不支持的图片格式: {ext}",
            "suggestion": f"支持的格式: {', '.join(sorted(constants.IMAGE_EXTENSIONS))}",
        }
    size = os.path.getsize(abspath)
    if size > IMAGE_MAX_BYTES:
        return {"error": f"图片过大: {size} 字节", "suggestion": "图片需小于 64MiB"}
    return {"success": True, "path": abspath, "media_type": guess_media_type(abspath), "size": size}
