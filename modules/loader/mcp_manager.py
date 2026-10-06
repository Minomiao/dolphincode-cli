"""MCP 服务器连接、工具注册与调用管理。

按 date/mcp_servers.json 建立 stdio / sse / http 连接，把远端 list_tools 的结果
注册为统一 mcp_ 前缀的工具，并提供调用分发与连接状态查询。

会话生命周期由每台服务器各自的常驻 Task 托管：上下文的进入/退出都在该 Task 内完成，
从而支持从任意调用方任务安全地单独断开（启停）与整体关闭。
"""
import asyncio
import json
import os
import re
import traceback
from contextlib import asynccontextmanager, suppress
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession

from modules import bootstrap as app_paths
from modules.bootstrap import constants
from modules.logger import get_logger

log = get_logger("Dolphin.mcp_manager")

# 工具注册名只允许 OpenAI function calling 的合法字符
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]")

# ${VAR} 形式的取值，从环境变量（.env 已加载）展开
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")

_TRANSPORT_STDIO = "stdio"
_TRANSPORT_SSE = "sse"
_TRANSPORT_HTTP = "http"

# 控制类工具（非远端工具）：用于运行期安装/卸载/查看/重载 MCP 配置
_INSTALL_TOOL_NAME = "mcp_install"
_UNINSTALL_TOOL_NAME = "mcp_uninstall"
_LIST_TOOL_NAME = "mcp_list"
_RELOAD_TOOL_NAME = "mcp_reload"


def _expand_env(value):
    """递归展开字符串中的 ${VAR} 引用（取环境变量，未定义为空串）。"""
    if isinstance(value, str):
        return _ENV_VAR_RE.sub(lambda m: os.getenv(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _resolve_transport(cfg: Dict[str, Any]) -> str:
    """确定服务器传输类型：显式 transport 优先，否则由 command 推断为 stdio。"""
    transport = cfg.get("transport")
    if transport:
        return transport
    if cfg.get("command"):
        return _TRANSPORT_STDIO
    return ""


@asynccontextmanager
async def _open_streams(cfg: Dict[str, Any]):
    """按配置打开传输层，统一产出 (read, write) 二元组。

    sse / http 均为远程连接，断开只释放我方连接，不影响远端服务；
    stdio 为本地子进程，退出上下文时由 SDK 回收该子进程。
    """
    transport = _resolve_transport(cfg)
    if transport == _TRANSPORT_STDIO:
        from mcp import StdioServerParameters, stdio_client
        params = StdioServerParameters(
            command=cfg["command"],
            args=[str(a) for a in cfg.get("args", [])],
            env=_expand_env(cfg.get("env")) or None,
            cwd=_expand_env(cfg.get("cwd")) or None,
        )
        async with stdio_client(params) as (read, write):
            yield read, write
    elif transport == _TRANSPORT_SSE:
        from mcp.client.sse import sse_client
        async with sse_client(
                cfg["url"], headers=_expand_env(cfg.get("headers")) or None) as (read, write):
            yield read, write
    elif transport == _TRANSPORT_HTTP:
        from mcp.client.streamable_http import streamablehttp_client
        async with streamablehttp_client(
                cfg["url"], headers=_expand_env(cfg.get("headers")) or None) as (read, write, _sid):
            yield read, write
    else:
        raise ValueError(f"未知或缺失的传输类型: {transport!r}（需配置 command 或 transport/url）")


def _mcp_user_output(text: str, error: bool = False) -> Dict[str, Any]:
    """构造 MCP 工具的精简终端标签：成功 [mcp] text，失败追加红色 Error。"""
    parts = [{"text": text}]
    if error:
        parts.append({"text": "Error", "style": "red"})
    return {"label": "mcp", "parts": parts}


def _normalize_call_result(result, display_name: str) -> Dict[str, Any]:
    """把 MCP CallToolResult 归化为下游可序列化的 dict，并附带精简展示标签。"""
    texts = []
    for block in getattr(result, "content", None) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            texts.append(getattr(block, "text", ""))
        elif block_type == "image":
            texts.append("[image]")
        else:
            texts.append(str(block))
    text = "\n".join(texts)

    if getattr(result, "isError", False):
        return {
            "error": text or "MCP 工具返回错误",
            "user_output": _mcp_user_output(display_name, error=True),
        }

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        payload = {"result": structured, "text": text} if text else {"result": structured}
    else:
        payload = {"result": text}
    payload["user_output"] = _mcp_user_output(display_name)
    return payload


def load_servers() -> Dict[str, dict]:
    """读取 date/mcp_servers.json 的 mcpServers 段，缺失或损坏返回空字典。"""
    path = getattr(app_paths, "MCP_FILE", None)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except PermissionError as e:
        log.warning(f"无权限读取 mcp_servers.json: {e}")
        return {}
    except json.JSONDecodeError as e:
        log.warning(f"mcp_servers.json 格式错误: {e}")
        return {}
    except Exception as e:
        log.warning(f"读取 mcp_servers.json 发生意外错误: {e}")
        return {}

    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


def _write_servers(servers: Dict[str, dict]) -> bool:
    """原子写回 date/mcp_servers.json 的 mcpServers 段。"""
    path = getattr(app_paths, "MCP_FILE", None)
    if not path:
        return False
    directory = os.path.dirname(path)
    try:
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        tmp_path = path + ".tmp"
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({"mcpServers": servers}, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except PermissionError as e:
        log.warning(f"无权限写入 mcp_servers.json: {e}")
    except OSError as e:
        log.warning(f"写入 mcp_servers.json 失败 (操作系统错误): {e}")
    except Exception as e:
        log.warning(f"写入 mcp_servers.json 发生意外错误: {e}")
    return False


def save_server_enabled(name: str, enabled: bool) -> bool:
    """把某台服务器的启用状态持久化到 mcp_servers.json。"""
    servers = load_servers()
    if name not in servers:
        log.warning(f"mcp_servers.json 中不存在服务器: {name}")
        return False
    servers[name]["enabled"] = enabled
    return _write_servers(servers)


def ensure_servers_file() -> bool:
    """确保 date/mcp_servers.json 存在（首次运行时创建空白内容）。"""
    path = getattr(app_paths, "MCP_FILE", None)
    if not path or os.path.exists(path):
        return False
    if _write_servers({}):
        log.info(f"已创建空白 MCP 配置文件: {path}")
        return True
    return False


class _ServerHandle:
    """一台服务器的常驻持有者。

    会话上下文的进入与退出都在持有者的 Task 内完成，因此无论调用方
    （工具调用 Task / 主循环 Task）是谁，断开时都不会出现
    “cancel scope exited in a different task” 的问题。
    """

    def __init__(self):
        self.task: Optional[asyncio.Task] = None
        self.session: Optional[ClientSession] = None
        # 建连完成（成功或失败）后置位，供 connect_server 等待
        self.ready = asyncio.Event()
        # 请求持有者退出上下文
        self.stop = asyncio.Event()
        # 建连阶段或持有时发生的异常
        self.error: Optional[BaseException] = None


class MCPManager:
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        # 注册名（mcp_ 前缀，加载时确定）→ (server_name, 原始工具名)
        self._tool_map: Dict[str, tuple] = {}
        # 注册名 → {description, input_schema}
        self._tool_info: Dict[str, Dict[str, Any]] = {}
        # 服务器名 → 该服务器注册的工具名列表（断开时精准注销）
        self._server_tools: Dict[str, List[str]] = {}
        # 服务器名 → 常驻持有者（会话上下文的进入/退出都在其 Task 内）
        self._handles: Dict[str, _ServerHandle] = {}
        # 服务器名 → 配置（连接期缓存，供 /mcp 展示）
        self._server_configs: Dict[str, dict] = {}
        # 服务器名 → 最近一次连接失败原因
        self._errors: Dict[str, str] = {}
        log.debug("初始化 MCPManager")

    def register_server_tools(self, server_name: str, tools: List[Dict[str, Any]]):
        """将会话建立后发现的 MCP 工具注册为统一 mcp_ 前缀的注册名。

        注册名在加载时确定并存入映射表，调用时零歧义查表；
        外部工具名中的非法字符（OpenAI 工具名仅允许字母数字与 _-）替换为下划线，
        注册名冲突在注册时报错。

        Args:
            server_name: MCP 服务器名
            tools: list_tools 归一化后的工具描述列表 [{name, description, input_schema}]
        """
        registered_names = []
        for tool in tools:
            raw_name = tool.get("name", "")
            registered = _SAFE_NAME_RE.sub("_", f"mcp_{server_name}_{raw_name}")
            if registered in self._tool_map:
                raise ValueError(f"MCP 工具注册名冲突: {registered}")
            self._tool_map[registered] = (server_name, raw_name)
            self._tool_info[registered] = {
                "description": tool.get("description", ""),
                "input_schema": tool.get("input_schema") or {
                    "type": "object", "properties": {}, "required": []
                },
            }
            registered_names.append(registered)
        self._server_tools[server_name] = registered_names
        log.info(f"MCP 服务器 {server_name} 注册 {len(tools)} 个工具")

    def unregister_server(self, server_name: str):
        """注销某台服务器注册的全部工具。"""
        for tool_name in self._server_tools.pop(server_name, []):
            self._tool_map.pop(tool_name, None)
            self._tool_info.pop(tool_name, None)

    async def connect_server(self, name: str, cfg: Dict[str, Any] = None) -> bool:
        """建立单台服务器连接并注册其工具，失败记录原因并返回 False。

        实际的会话上下文在独立的常驻 Task 内进入，调用方仅在 ready 上等待，
        因此本方法可从任意 Task 调用。
        """
        if name in self.sessions:
            return True
        if cfg is None:
            cfg = self._server_configs.get(name) or load_servers().get(name)
        if not cfg:
            self._errors[name] = "未找到服务器配置"
            log.warning(f"MCP 服务器缺少配置: {name}")
            return False

        self._server_configs[name] = cfg
        self._errors.pop(name, None)

        handle = _ServerHandle()
        handle.task = asyncio.ensure_future(self._run_server(name, cfg, handle))
        self._handles[name] = handle

        try:
            await handle.ready.wait()
        except asyncio.CancelledError:
            # 建连过程被取消：回收持有者任务后继续传播取消
            self._handles.pop(name, None)
            await self._stop_handle(name, handle)
            raise

        if handle.error is not None:
            self._errors[name] = str(handle.error) or handle.error.__class__.__name__
            log.error(f"MCP 服务器 {name} 连接失败: {handle.error}\n"
                      f"{''.join(traceback.format_exception(handle.error))}")
            self._handles.pop(name, None)
            return False

        self.sessions[name] = handle.session
        log.info(f"MCP 服务器 {name} 已连接（{len(self._server_tools.get(name, []))} 个工具）")
        return True

    async def _run_server(self, name: str, cfg: Dict[str, Any], handle: _ServerHandle):
        """常驻持有者：进入会话上下文、注册工具，直到收到停止请求或本任务被取消。

        所有上下文的进入/退出都发生在本 Task 内，从根本上满足 anyio 的任务亲和要求。
        """
        try:
            async with _open_streams(cfg) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    tools = [
                        {"name": t.name, "description": t.description or "",
                         "input_schema": t.inputSchema}
                        for t in tools_result.tools
                    ]
                    self.register_server_tools(name, tools)
                    handle.session = session
                    handle.ready.set()
                    await handle.stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            handle.error = e
            if handle.session is not None:
                self._errors[name] = str(e) or e.__class__.__name__
                log.error(f"MCP 服务器 {name} 会话异常结束: {e}")
        finally:
            handle.ready.set()
            self.unregister_server(name)
            self.sessions.pop(name, None)

    async def _stop_handle(self, name: str, handle: _ServerHandle,
                           timeout: int = None):
        """请求持有者任务在自身内部退出上下文并等待其收尾（超时则强制取消）。

        取消同样会让上下文在持有者 Task 内展开退出，故不影响任务亲和。
        """
        task = handle.task
        if task is None or task.done():
            return
        timeout = constants.MCP_TIMEOUT if timeout is None else timeout
        handle.stop.set()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            log.warning(f"MCP 服务器 {name} 关闭超时({timeout}s)，强制取消")
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        except asyncio.CancelledError:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            raise
        except Exception as e:
            log.warning(f"MCP 服务器 {name} 关闭时异常: {e}")

    async def disconnect_server(self, name: str):
        """断开单台服务器：注销工具并让持有者任务退出会话上下文。"""
        self.sessions.pop(name, None)
        handle = self._handles.pop(name, None)
        if handle is not None:
            await self._stop_handle(name, handle)
        self.unregister_server(name)
        log.info(f"MCP 服务器 {name} 已断开")

    async def connect_all(self, servers: Dict[str, dict] = None) -> int:
        """连接全部启用的服务器（串行建连，单台失败不影响其余）。"""
        if servers is None:
            ensure_servers_file()
            servers = load_servers()
        for name, cfg in servers.items():
            if not cfg.get("enabled", True):
                self._server_configs[name] = cfg
                continue
            await self.connect_server(name, cfg)
        return len(self.sessions)

    async def reload(self) -> Dict[str, Any]:
        """重新读取配置文件并对齐连接：连新增/新启用，断已禁用/已移除。

        供运行期安装或修改 MCP 配置后即时生效，无需重启。
        """
        ensure_servers_file()
        servers = load_servers()

        # 配置中已移除的服务器：断开并清理状态
        for name in list(self._server_configs):
            if name in servers:
                continue
            if name in self.sessions:
                await self.disconnect_server(name)
            self._server_configs.pop(name, None)
            self._errors.pop(name, None)

        connected, failed = [], []
        for name, cfg in servers.items():
            self._server_configs[name] = cfg
            if not cfg.get("enabled", True):
                if name in self.sessions:
                    await self.disconnect_server(name)
                continue
            if name in self.sessions:
                continue
            if await self.connect_server(name, cfg):
                connected.append(name)
            else:
                failed.append(name)

        log.info(f"MCP 配置重载完成: 连接 {connected}, 失败 {failed}")
        return {"success": True, "connected": connected, "failed": failed}

    async def _handle_reload(self) -> Dict[str, Any]:
        """mcp_reload 控制工具：执行重载并返回精简结果。"""
        result = await self.reload()
        connected = result.get("connected") or []
        failed = result.get("failed") or []
        return {
            "success": True,
            "connected": connected,
            "failed": failed,
            "servers": [info["name"] for info in self.list_servers()],
            "user_output": _mcp_user_output(
                f"reload · 连接 {len(connected)} · 失败 {len(failed)}",
                error=bool(failed)),
        }

    def _handle_install(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mcp_install 控制工具：把一台服务器配置写入 mcp_servers.json。"""
        name = str(arguments.get("name") or "").strip()
        if not name:
            return {"error": "缺少 name 参数",
                    "user_output": _mcp_user_output("install", error=True)}

        cfg = self._build_server_config(arguments)
        if "error" in cfg:
            cfg["user_output"] = _mcp_user_output(f"install {name}", error=True)
            return cfg

        servers = load_servers()
        servers[name] = cfg
        if not _write_servers(servers):
            return {"error": "写入 mcp_servers.json 失败",
                    "user_output": _mcp_user_output(f"install {name}", error=True)}
        self._server_configs[name] = cfg
        log.info(f"已写入 MCP 服务器配置: {name}")
        return {
            "success": True,
            "name": name,
            "config": cfg,
            "hint": "调用 mcp_reload 使配置生效",
            "user_output": _mcp_user_output(f"install {name}"),
        }

    @staticmethod
    def _build_server_config(arguments: Dict[str, Any]) -> Dict[str, Any]:
        """由 mcp_install 参数构造服务器配置，非法时返回 {"error": ...}。"""
        transport = arguments.get("transport") or (
            _TRANSPORT_STDIO if arguments.get("command") else "")
        if transport == _TRANSPORT_STDIO:
            if not arguments.get("command"):
                return {"error": "stdio 传输需要 command 参数"}
            cfg = {"transport": transport, "command": arguments["command"]}
            for key in ("args", "env", "cwd"):
                if arguments.get(key):
                    cfg[key] = arguments[key]
        elif transport in (_TRANSPORT_SSE, _TRANSPORT_HTTP):
            if not arguments.get("url"):
                return {"error": f"{transport} 传输需要 url 参数"}
            cfg = {"transport": transport, "url": arguments["url"]}
            if arguments.get("headers"):
                cfg["headers"] = arguments["headers"]
        else:
            return {"error": "需要 command（stdio）或 transport/url（sse/http）"}
        cfg["enabled"] = arguments.get("enabled", True)
        return cfg

    async def _handle_uninstall(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """mcp_uninstall 控制工具：从 mcp_servers.json 移除并断开一台服务器。"""
        name = str(arguments.get("name") or "").strip()
        if not name:
            return {"error": "缺少 name 参数",
                    "user_output": _mcp_user_output("uninstall", error=True)}

        servers = load_servers()
        if name not in servers:
            return {"error": f"未安装的 MCP 服务器: {name}",
                    "user_output": _mcp_user_output(f"uninstall {name}", error=True)}
        servers.pop(name)
        if not _write_servers(servers):
            return {"error": "写入 mcp_servers.json 失败",
                    "user_output": _mcp_user_output(f"uninstall {name}", error=True)}

        if name in self.sessions:
            await self.disconnect_server(name)
        self._server_configs.pop(name, None)
        self._errors.pop(name, None)
        log.info(f"已卸载 MCP 服务器配置: {name}")
        return {
            "success": True,
            "name": name,
            "message": f"已卸载 {name}",
            "user_output": _mcp_user_output(f"uninstall {name}"),
        }

    def _handle_list(self) -> Dict[str, Any]:
        """mcp_list 控制工具：以磁盘配置为准列出服务器及连接状态。"""
        servers = self.list_servers(load_servers())
        return {
            "success": True,
            "count": len(servers),
            "servers": servers,
            "user_output": _mcp_user_output(f"list · {len(servers)}"),
        }

    async def close_all(self):
        """断开全部连接并清空注册表（退出时调用；可重复调用）。"""
        for name in list(self._handles):
            handle = self._handles.pop(name, None)
            self.sessions.pop(name, None)
            if handle is None:
                continue
            try:
                await self._stop_handle(name, handle)
            except Exception as e:
                log.warning(f"关闭 MCP 服务器 {name} 失败: {e}")
        self.sessions.clear()
        self._tool_map.clear()
        self._tool_info.clear()
        self._server_tools.clear()

    def list_servers(self, configs: Dict[str, dict] = None) -> List[Dict[str, Any]]:
        """返回服务器展示信息（配置 + 运行时状态）。

        Args:
            configs: 待展示的配置字典；缺省用内存中连接期缓存的配置。
        """
        result = []
        for name, cfg in (self._server_configs if configs is None else configs).items():
            enabled = cfg.get("enabled", True)
            result.append({
                "name": name,
                "transport": _resolve_transport(cfg) or "-",
                "detail": cfg.get("url") or cfg.get("command") or "",
                "enabled": enabled,
                "connected": name in self.sessions,
                "tool_count": len(self._server_tools.get(name, [])),
                "error": self._errors.get(name, ""),
            })
        return result

    def set_server_enabled(self, name: str, enabled: bool) -> bool:
        """切换服务器启用状态并持久化，成功时同步内存配置。"""
        if not save_server_enabled(name, enabled):
            return False
        if name in self._server_configs:
            self._server_configs[name]["enabled"] = enabled
        return True

    def _resolve_tool_name(self, tool_name: str) -> Optional[str]:
        """别名兜底：把不规范的调用名解析回已注册名。

        兼容模型照抄 SKILL.md 写法的常见情形：去掉 mcp_ 前缀的 {server}_{raw}、
        仅 {raw}，以及大小写差异。仅在唯一命中时纠偏，歧义时返回 None。
        """
        lowered = tool_name.lower()
        matched = [
            registered
            for registered, (server, raw) in self._tool_map.items()
            if lowered in (registered.lower(), f"{server}_{raw}".lower(), raw.lower())
        ]
        return matched[0] if len(matched) == 1 else None

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if tool_name == _INSTALL_TOOL_NAME:
            return self._handle_install(arguments or {})
        if tool_name == _UNINSTALL_TOOL_NAME:
            return await self._handle_uninstall(arguments or {})
        if tool_name == _LIST_TOOL_NAME:
            return self._handle_list()
        if tool_name == _RELOAD_TOOL_NAME:
            return await self._handle_reload()
        log.info(f"调用 MCP 工具: {tool_name}, 参数: {arguments}")

        mapped = self._tool_map.get(tool_name)
        if mapped is None:
            resolved = self._resolve_tool_name(tool_name)
            if resolved is None:
                log.error(f"未注册的 MCP 工具: {tool_name}")
                raise ValueError(f"未注册的 MCP 工具: {tool_name}")
            log.info(f"MCP 工具名别名纠正: {tool_name} -> {resolved}")
            mapped = self._tool_map[resolved]

        server_name, actual_tool_name = mapped
        display_name = f"{server_name}/{actual_tool_name}"
        if server_name not in self.sessions:
            # 惰性重连：工具仍注册但会话已丢失时，尝试按配置重连一次
            cfg = self._server_configs.get(server_name) or load_servers().get(server_name)
            if cfg and cfg.get("enabled", True):
                log.info(f"MCP 服务器 {server_name} 未连接，尝试重连")
                await self.connect_server(server_name, cfg)
            if server_name not in self.sessions:
                log.error(f"MCP 服务器 {server_name} 未连接")
                raise ValueError(f"MCP 服务器 {server_name} 未连接")

        session = self.sessions[server_name]
        try:
            result = await asyncio.wait_for(
                session.call_tool(actual_tool_name, arguments),
                timeout=constants.MCP_TIMEOUT)
        except asyncio.TimeoutError:
            log.error(f"MCP 工具 {tool_name} 执行超时 ({constants.MCP_TIMEOUT}s)")
            return {"error": f"MCP 工具执行超时 ({constants.MCP_TIMEOUT}s)",
                    "user_output": _mcp_user_output(display_name, error=True)}
        except Exception as e:
            log.error(f"MCP 工具 {tool_name} 执行失败: {e}\n{traceback.format_exc()}")
            return {"error": "MCP 工具执行过程中发生内部错误",
                    "user_output": _mcp_user_output(display_name, error=True)}

        log.debug(f"MCP 工具执行结果: {result}")
        return _normalize_call_result(result, display_name)

    def get_all_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_info["description"],
                    "parameters": tool_info["input_schema"]
                }
            }
            for tool_name, tool_info in self._tool_info.items()
        ]

    def get_control_tools(self) -> List[Dict[str, Any]]:
        """MCP 控制类工具（非远端工具）：安装 / 卸载 / 列出 / 重载。

        始终提供，即使当前未配置任何服务器（此时仍可能需要安装）。
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": _INSTALL_TOOL_NAME,
                    "description": "安装或更新一台 MCP 服务器：把配置写入 date/mcp_servers.json。"
                                   "stdio 传 command/args/env，sse/http 传 url/headers。"
                                   "写完后调用 mcp_reload 使其生效",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "服务器名称（唯一标识）"},
                            "transport": {
                                "type": "string",
                                "enum": [_TRANSPORT_STDIO, _TRANSPORT_SSE, _TRANSPORT_HTTP],
                                "description": "传输类型；省略时按 command 推断为 stdio",
                            },
                            "command": {"type": "string", "description": "stdio 可执行命令"},
                            "args": {
                                "type": "array", "items": {"type": "string"},
                                "description": "stdio 命令参数",
                            },
                            "env": {
                                "type": "object", "additionalProperties": {"type": "string"},
                                "description": "stdio 环境变量（密钥可用 ${VAR} 从 .env 展开）",
                            },
                            "cwd": {"type": "string", "description": "stdio 工作目录"},
                            "url": {"type": "string", "description": "sse/http 服务地址"},
                            "headers": {
                                "type": "object", "additionalProperties": {"type": "string"},
                                "description": "sse/http 请求头",
                            },
                            "enabled": {"type": "boolean", "description": "是否启用（默认 true）"},
                        },
                        "required": ["name"],
                    },
                }
            },
            {
                "type": "function",
                "function": {
                    "name": _UNINSTALL_TOOL_NAME,
                    "description": "卸载一台 MCP 服务器：从 date/mcp_servers.json 移除其配置，"
                                   "若已连接则同时断开并注销其工具",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "要卸载的服务器名称"},
                        },
                        "required": ["name"],
                    },
                }
            },
            {
                "type": "function",
                "function": {
                    "name": _LIST_TOOL_NAME,
                    "description": "列出 date/mcp_servers.json 中已配置的全部 MCP 服务器"
                                   "（名称、传输类型、启用状态、是否已连接、工具数）",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            },
            {
                "type": "function",
                "function": {
                    "name": _RELOAD_TOOL_NAME,
                    "description": "重新读取 date/mcp_servers.json：连接新增或新启用的 MCP "
                                   "服务器、断开已禁用或已移除的，用于安装或修改 MCP 配置后即时生效",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                }
            },
        ]

    def get_tool_names(self) -> List[str]:
        return list(self._tool_map.keys())


_mcp_manager = None


def get_mcp_manager() -> MCPManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager
