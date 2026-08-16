import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from modules.logger import get_logger
from modules.bootstrap import constants
from . import backup_manager

log = get_logger("Dolphin.file_operation")

MAX_FILE_SIZE = constants.MAX_FILE_SIZE
MAX_LINE_COUNT = constants.MAX_LINE_COUNT


def _check_dpc_restriction(absolute_path: str) -> Tuple[bool, Optional[str]]:
    from modules.chater import dpc_manager
    current = os.path.dirname(os.path.abspath(absolute_path))
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    while True:
        dpc_path = os.path.join(current, '.dpc')
        if os.path.exists(dpc_path):
            rel = os.path.relpath(absolute_path, current)
            allowed, msg = dpc_manager.is_path_allowed(current, rel)
            if not allowed:
                return False, msg
        parent = os.path.dirname(current)
        if parent == current or os.path.commonpath([parent, project_root]) != project_root:
            break
        current = parent
    return True, None


def _resolve_and_validate(work_path: Path, file_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """解析路径并验证：1)在工作目录内 2)不含符号链接
    
    Returns:
        (resolved_path, None) 或 (None, error_message)
    """
    file_path_obj = Path(file_path)
    if file_path_obj.is_absolute():
        resolved_path = file_path_obj.resolve()
    else:
        resolved_path = (work_path / file_path_obj).resolve()
    
    # 检查路径是否在工作目录内
    try:
        resolved_path.relative_to(work_path)
    except ValueError:
        return None, f"路径必须是工作目录的子目录: {work_path}"
    
    # 检查符号链接：工作目录下任何组件是 symlink 都拒绝
    try:
        current = resolved_path
        while current != work_path and current != current.parent:
            if current.is_symlink():
                return None, f"路径包含符号链接，不允许: {current}"
            current = current.parent
    except OSError as e:
        log.warning(f"符号链接检查失败: {e}")
    
    return resolved_path, None

class FileOperation:
    """文件操作管理器"""
    
    def __init__(self) -> None:
        log.info("FileOperation 初始化完成")
    
    def get_work_directory(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """获取工作目录"""
        try:
            from modules.main_server import config
            work_directory = config.load_config().get('work_directory', 'workplace')
            return {
                "success": True,
                "work_directory": work_directory
            }
        except Exception as e:
            log.error(f"获取工作目录失败: {e}")
            return {
                "error": f"获取工作目录失败: {str(e)}"
            }
    
    def create_file(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """创建文件"""
        start = time.perf_counter()
        try:
            # 获取参数
            file_path = request_data.get('file_path')
            content = request_data.get('content')
            encoding = request_data.get('encoding', 'utf-8')
            work_directory = request_data.get('work_directory')
            
            if not file_path:
                return {"error": "缺少 file_path 参数"}
            if content is None:
                return {"error": "缺少 content 参数"}
            if not work_directory:
                return {"error": "缺少 work_directory 参数"}

            # 去除行号标记（AI可能把行号标记作为内容的一部分）
            import re
            line_number_pattern = re.compile(r'^\d+\|\s*')

            def strip_line_number(text):
                if text:
                    return line_number_pattern.sub('', text)
                return text

            # 处理多行内容，对每一行都去除行号标记
            lines = content.split('\n')
            lines = [strip_line_number(line) for line in lines]
            content = '\n'.join(lines)

            # 验证内容大小
            content_size = len(content.encode(encoding))
            if content_size > MAX_FILE_SIZE:
                return {
                    "error": f"文件内容过大: {content_size} 字节，最大允许: {MAX_FILE_SIZE} 字节"
                }
            
            # 验证行数
            line_count = len(content.splitlines())
            if line_count > MAX_LINE_COUNT:
                return {
                    "error": f"文件行数过多: {line_count} 行，最大允许: {MAX_LINE_COUNT} 行"
                }
            
            # 构建完整路径（含符号链接检测）
            work_path = Path(work_directory).resolve()
            resolved_path, path_err = _resolve_and_validate(work_path, file_path)
            if path_err:
                return {"error": path_err}
            
            allowed, msg = _check_dpc_restriction(str(resolved_path))
            if not allowed:
                return {"error": msg}

            # 确保父目录存在
            parent_dir = resolved_path.parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)
            
            # 检查文件是否存在，决定操作类型
            file_exists_before_write = resolved_path.exists()
            action_type = "modify" if file_exists_before_write else "create"

            # 写入文件
            with open(resolved_path, 'w', encoding=encoding, errors='ignore') as f:
                f.write(content)

            # 记录备份（如果有）
            backup_path = None
            pending_count = 0
            try:
                backup_mgr = backup_manager.get_backup_manager()
                if backup_mgr:
                    backup_path = backup_mgr.backup_file(str(Path(file_path)), work_directory, action=action_type)
                    backup_mgr.record_change(
                        action=action_type,
                        file_path=str(Path(file_path)),
                        work_dir=work_directory
                    )
                    pending_count = backup_mgr.get_pending_changes_count()
            except Exception as e:
                log.warning(f"备份操作失败: {e}")
            
            elapsed = time.perf_counter() - start
            log.info(f"创建文件完成: {file_path}, 耗时={elapsed:.3f}s, 大小={content_size}字节")
            return {
                "success": True,
                "file_path": str(resolved_path.relative_to(work_path)),
                "encoding": encoding,
                "content_size": content_size,
                "line_count": line_count,
                "backup_path": backup_path,
                "pending_changes": pending_count,
                "message": f"文件已创建: {file_path}"
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            log.error(f"创建文件失败: {file_path}, 耗时={elapsed:.3f}s, 错误: {e}")
            return {
                "error": f"创建文件失败: {str(e)}"
            }
    
    def read_file(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """读取文件"""
        start = time.perf_counter()
        file_path = request_data.get('file_path', '')
        try:
            # 获取参数
            file_path = request_data.get('file_path')
            encoding = request_data.get('encoding', 'utf-8')
            offset = request_data.get('offset', 0)
            # limit 采用 100 行冗余设计：对外声明 1000 行，实际默认 1100 行
            limit = request_data.get('limit', MAX_LINE_COUNT)
            work_directory = request_data.get('work_directory')
            
            if not file_path:
                return {"error": "缺少 file_path 参数"}
            if not work_directory:
                return {"error": "缺少 work_directory 参数"}
            
            # 构建完整路径（含符号链接检测）
            work_path = Path(work_directory).resolve()
            resolved_path, path_err = _resolve_and_validate(work_path, file_path)
            if path_err:
                return {"error": path_err}
            
            allowed, msg = _check_dpc_restriction(str(resolved_path))
            if not allowed:
                return {"error": msg}

            # 检查文件是否存在
            if not resolved_path.exists():
                return {"error": f"文件不存在: {file_path}"}
            if not resolved_path.is_file():
                return {"error": f"路径不是文件: {file_path}"}
            
            # 检查文件大小
            file_size = resolved_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                return {
                    "error": f"文件过大: {file_size} 字节，最大允许: {MAX_FILE_SIZE} 字节"
                }
            
            # 读取文件内容
            with open(resolved_path, 'r', encoding=encoding, errors='ignore') as f:
                all_lines = f.readlines()
            
            total_lines = len(all_lines)
            
            # 验证偏移量
            if offset >= total_lines:
                return {
                    "success": True,
                    "file_path": str(resolved_path.relative_to(work_path)),
                    "encoding": encoding,
                    "content": "",
                    "line_count": 0,
                    "total_lines": total_lines,
                    "offset": offset,
                    "limit": limit,
                    "has_more": False,
                    "size": file_size,
                    "message": f"已到达文件末尾，文件共 {total_lines} 行"
                }
            
            # 计算读取范围
            end_line = min(offset + limit, total_lines)
            selected_lines = all_lines[offset:end_line]

            lines_out = [line.rstrip('\n\r') if line else '' for line in selected_lines]
            content = "\n".join(lines_out)

            elapsed = time.perf_counter() - start
            log.info(f"读取文件完成: {file_path}, 耗时={elapsed:.3f}s, 行数={len(selected_lines)}/{total_lines}")
            return {
                "success": True,
                "file_path": str(resolved_path.relative_to(work_path)),
                "encoding": encoding,
                "content": content,
                "line_count": len(selected_lines),
                "total_lines": total_lines,
                "offset": offset,
                "limit": limit,
                "start_line": offset + 1,
                "end_line": end_line,
                "has_more": end_line < total_lines,
                "size": file_size,
                "line_number_format": "N|content (N is the 1-based line number). Numbers and '|' are annotations ONLY, they are NOT part of the actual file content.",
                "message": f"读取第 {offset + 1}-{end_line} 行，共 {total_lines} 行"
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            log.error(f"读取文件失败: {file_path}, 耗时={elapsed:.3f}s, 错误: {e}")
            return {
                "error": f"读取文件失败: {str(e)}"
            }
    
    @staticmethod
    def _strip_whitespace(s: str) -> str:
        """去除所有空白字符（空格、制表符、换行等）"""
        return ''.join(s.split())

    def _find_str_match(self, content: str, target: str) -> Tuple[int, Optional[str]]:
        """
        三级匹配策略查找 target 在 content 中的位置。
        返回 (index, method) 或 (-1, None)。
        1. 原始格式精确匹配
        2. 去除所有空白后匹配
        3. 模糊匹配（阈值 95%）
        """
        # 第一级：原始格式精确匹配
        idx = content.find(target)
        if idx != -1:
            return idx, "exact"

        # 第二级：去除所有空白后匹配
        stripped_content = self._strip_whitespace(content)
        stripped_target = self._strip_whitespace(target)
        if stripped_target:
            stripped_idx = stripped_content.find(stripped_target)
            if stripped_idx != -1:
                # 将去空白后的位置映射回原始内容的位置
                count = 0
                for i, ch in enumerate(content):
                    if not ch.isspace():
                        if count == stripped_idx:
                            return i, "whitespace_stripped"
                        count += 1
                return -1, None

        # 第三级：模糊匹配（95% 以上相似度）
        if len(target) < 10:
            return -1, None

        from difflib import SequenceMatcher

        target_len = len(target)
        content_len = len(content)
        window_margin = max(int(target_len * 0.2), 20)
        window_size = target_len + window_margin
        step = max(window_size // 4, 1)

        best_ratio = 0
        best_start = -1

        pos = 0
        while pos < content_len:
            end = min(pos + window_size, content_len)
            chunk = content[pos:end]
            matcher = SequenceMatcher(None, chunk, target)
            match_blocks = matcher.get_matching_blocks()
            total_match = sum(block.size for block in match_blocks)
            ratio = (2.0 * total_match) / (len(chunk) + len(target) + 0.001)
            ratio = min(ratio, 1.0)

            if ratio > best_ratio:
                best_ratio = ratio
                if match_blocks:
                    longest = max(match_blocks[:-1], key=lambda b: b.size)
                    best_start = pos + longest.a

            pos += step

        if best_ratio >= 0.95:
            return best_start, f"fuzzy({best_ratio:.1%})"

        return -1, None

    def modify_file(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """修改文件 - 基于字符串查找替换"""
        start = time.perf_counter()
        file_path = request_data.get('file_path', '')
        try:
            # 获取参数
            file_path = request_data.get('file_path')
            old_str = request_data.get('old_str')
            new_str = request_data.get('new_str')
            encoding = request_data.get('encoding', 'utf-8')
            work_directory = request_data.get('work_directory')
            
            if not file_path:
                return {"error": "缺少 file_path 参数"}
            if old_str is None:
                return {"error": "缺少 old_str 参数"}
            if new_str is None:
                return {"error": "缺少 new_str 参数"}
            if not work_directory:
                return {"error": "缺少 work_directory 参数"}

            # 构建完整路径（含符号链接检测）
            work_path = Path(work_directory).resolve()
            resolved_path, path_err = _resolve_and_validate(work_path, file_path)
            if path_err:
                return {"error": path_err}
            
            allowed, msg = _check_dpc_restriction(str(resolved_path))
            if not allowed:
                return {"error": msg}

            # 检查文件是否存在
            if not resolved_path.exists():
                return {"error": f"文件不存在: {file_path}"}
            if not resolved_path.is_file():
                return {"error": f"路径不是文件: {file_path}"}
            
            file_size = resolved_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                return {"error": f"文件超过最大限制 ({MAX_FILE_SIZE / 1024 / 1024:.0f}MB)"}
            
            # 读取文件内容
            with open(resolved_path, 'r', encoding=encoding, errors='ignore') as f:
                original_content = f.read()
            
            # 三级匹配策略查找 old_str
            index, match_method = self._find_str_match(original_content, old_str)
            if index == -1:
                return {
                    "error": "未在文件中找到匹配的原始字符串",
                    "hint": "请确认 old_str 的内容与文件中的内容完全一致，或调整使其更准确"
                }
            
            # 构建新内容（只替换第一次出现）
            new_content = original_content[:index] + new_str + original_content[index + len(old_str):]
            
            # 计算行数变化
            old_line_count = old_str.count('\n')
            new_line_count = new_str.count('\n')
            
            # 备份文件
            backup_path = None
            try:
                backup_mgr = backup_manager.get_backup_manager()
                if backup_mgr:
                    backup_path = backup_mgr.backup_file(str(Path(file_path)), work_directory, action="modify")
            except Exception as e:
                log.warning(f"备份操作失败: {e}")
            
            # 写入新内容
            with open(resolved_path, 'w', encoding=encoding, errors='ignore') as f:
                f.write(new_content)
            
            # 记录变更
            pending_count = 0
            try:
                backup_mgr = backup_manager.get_backup_manager()
                if backup_mgr:
                    backup_mgr.record_change(
                        action="modify",
                        file_path=str(Path(file_path)),
                        work_dir=work_directory
                    )
                    pending_count = backup_mgr.get_pending_changes_count()
            except Exception as e:
                log.warning(f"记录变更失败: {e}")
            
            new_content_size = len(new_content.encode(encoding))
            
            elapsed = time.perf_counter() - start
            log.info(f"修改文件完成: {file_path}, 耗时={elapsed:.3f}s, 新大小={new_content_size}字节")
            return {
                "success": True,
                "file_path": str(resolved_path.relative_to(work_path)),
                "encoding": encoding,
                "old_lines": old_line_count,
                "new_lines": new_line_count,
                "new_content_size": new_content_size,
                "backup_path": backup_path,
                "pending_changes": pending_count,
                "message": f"文件已修改: {file_path}"
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            log.error(f"修改文件失败: {file_path}, 耗时={elapsed:.3f}s, 错误: {e}")
            return {
                "error": f"修改文件失败: {str(e)}"
            }
    
    def delete_file(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """删除文件"""
        start = time.perf_counter()
        file_path = request_data.get('file_path', '')
        try:
            # 获取参数
            file_path = request_data.get('file_path')
            work_directory = request_data.get('work_directory')
            
            if not file_path:
                return {"error": "缺少 file_path 参数"}
            if not work_directory:
                return {"error": "缺少 work_directory 参数"}
            
            # 构建完整路径（含符号链接检测）
            work_path = Path(work_directory).resolve()
            resolved_path, path_err = _resolve_and_validate(work_path, file_path)
            if path_err:
                return {"error": path_err}
            
            allowed, msg = _check_dpc_restriction(str(resolved_path))
            if not allowed:
                return {"error": msg}

            # 检查文件是否存在
            if not resolved_path.exists():
                return {"error": f"文件不存在: {file_path}"}
            if not resolved_path.is_file():
                return {"error": f"路径不是文件: {file_path}"}
            
            file_size = resolved_path.stat().st_size
            
            # 备份文件
            backup_path = None
            try:
                backup_mgr = backup_manager.get_backup_manager()
                if backup_mgr:
                    backup_path = backup_mgr.backup_file(str(Path(file_path)), work_directory, action="delete")
            except Exception as e:
                log.warning(f"备份操作失败: {e}")
            
            # 实际删除文件
            resolved_path.unlink()
            
            # 记录变更
            pending_count = 0
            try:
                backup_mgr = backup_manager.get_backup_manager()
                if backup_mgr:
                    backup_mgr.record_change(
                        action="delete",
                        file_path=str(Path(file_path)),
                        work_dir=work_directory
                    )
                    pending_count = backup_mgr.get_pending_changes_count()
            except Exception as e:
                log.warning(f"记录变更失败: {e}")
            
            elapsed = time.perf_counter() - start
            log.info(f"删除文件完成: {file_path}, 耗时={elapsed:.3f}s, 大小={file_size}字节")
            return {
                "success": True,
                "file_path": str(resolved_path.relative_to(work_path)),
                "file_size": file_size,
                "backup_path": backup_path,
                "pending_changes": pending_count,
                "message": f"文件已删除: {file_path}"
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            log.error(f"删除文件失败: {file_path}, 耗时={elapsed:.3f}s, 错误: {e}")
            return {
                "error": f"删除文件失败: {str(e)}"
            }
    
    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """处理文件操作请求"""
        operation_type = request.get("operation_type")
        
        if operation_type == "get_work_directory":
            return self.get_work_directory(request)
        elif operation_type == "create_file":
            return self.create_file(request)
        elif operation_type == "read_file":
            return self.read_file(request)
        elif operation_type == "modify_file":
            return self.modify_file(request)
        elif operation_type == "delete_file":
            return self.delete_file(request)
        else:
            return {"error": "未知的操作类型"}

# 单例模式
_file_operation = None

def get_file_operation() -> FileOperation:
    global _file_operation
    if _file_operation is None:
        _file_operation = FileOperation()
    return _file_operation