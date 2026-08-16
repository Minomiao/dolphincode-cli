import asyncio
import traceback
from typing import Dict, List, Any, Optional
from mcp.client.session import ClientSession
from modules.logger import get_logger
from modules.bootstrap import constants

log = get_logger("Dolphin.mcp_manager")


class MCPManager:
    def __init__(self):
        self.sessions: Dict[str, ClientSession] = {}
        self.tools: Dict[str, Dict[str, Any]] = {}
        log.debug("初始化 MCPManager")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        log.info(f"调用 MCP 工具: {tool_name}, 参数: {arguments}")
        if "." not in tool_name:
            log.error(f"工具名称格式错误: {tool_name}")
            raise ValueError(f"工具名称格式错误: {tool_name}")

        server_name, actual_tool_name = tool_name.split(".", 1)

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
            return {"error": f"MCP 工具执行超时 ({constants.MCP_TIMEOUT}s)"}
        except Exception as e:
            log.error(f"MCP 工具 {tool_name} 执行失败: {e}\n{traceback.format_exc()}")
            return {"error": "MCP 工具执行过程中发生内部错误"}

        log.debug(f"MCP 工具执行结果: {result}")

        return result
    
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
            for tool_name, tool_info in self.tools.items()
        ]
    
    def get_tool_names(self) -> List[str]:
        return list(self.tools.keys())


_mcp_manager = None


def get_mcp_manager() -> MCPManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager
