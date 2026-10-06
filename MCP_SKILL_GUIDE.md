# dolphincode Skill 使用说明

## 概述

dolphincode 通过技能（Skills）系统扩展 AI 能力，AI 可自动调用工具完成文件操作、计算、搜索等任务。

## 内置技能

### calculator — 数学计算与时间
| 工具 | 说明 |
|------|------|
| `calculate(expression)` | 通过 sympy 求值数学表达式（支持 + - * / **、sqrt、sin/cos/tan、log、pi、e 等） |
| `get_current_time()` | 返回当前日期时间字符串 |

### file_reader — 文件读取与搜索
| 工具 | 说明 |
|------|------|
| `get_work_directory()` | 返回当前工作目录 |
| `search_files(pattern, ...)` | 按名称或内容搜索（最多 500 条结果，跳过 >10MB 文件） |
| `list_directory(path, ...)` | 树状视图列出目录（最多 1000 个文件，深度 10） |
| `read_file(path, ...)` | 分页读取文件内容（每次最多 1000 行，最大 10MB） |

### file_manager — 文件管理
| 工具 | 说明 |
|------|------|
| `set_work_directory(path)` | 切换工作目录（仅限子目录，支持 `..`，越界自动回退） |
| `create_file(path, content)` | 创建文件并写入内容（最大 10MB，1000 行） |
| `modify_file(path, old_string, new_string)` | 字符串查找替换修改（三级匹配） |
| `delete_file(path)` | 删除文件（需用户确认） |

### powershell_executor — PowerShell 脚本执行
| 工具 | 说明 |
|------|------|
| `run_script(script, timeout, wait_time)` | 异步执行 PowerShell 脚本（需用户确认） |
| `check_script(command_id, wait_time)` | 轮询后台命令状态和输出 |
| `kill_command(command_id)` | 强制终止后台命令 |

超时后命令继续在后台运行，不自动杀死。程序退出时通过 `atexit` + signal 自动清理所有子进程。

### random_generator — 随机生成
| 工具 | 说明 |
|------|------|
| `random_int(min, max)` | 随机整数 |
| `random_float(min, max)` | 随机浮点数 |
| `random_choice(choices)` | 从列表中随机选取一项 |
| `random_password(length, ...)` | 可配置字符集的随机密码 |

### web_search — 网络搜索
| 工具 | 说明 |
|------|------|
| `search(query, num_results)` | Bing 搜索（jieba 关键字相关性过滤） |
| `fetch(url)` | 解析指定网址的网页内容 |

### git — Git 版本控制
| 工具 | 说明 |
|------|------|
| `git_init()` | 初始化仓库并自动生成 `.gitignore`（同步 `.dpc` 屏蔽规则） |
| `git_status()` | 查看暂存区与工作区变更 |
| `git_diff(path)` | 查看未暂存差异，`path` 可限定单个文件 |
| `git_add(paths)` | 暂存文件，`.dpc` 屏蔽的路径自动跳过 |
| `git_commit(message)` | 提交更改（需用户确认，提交信息必须使用英文） |
| `git_log(max_count)` | 查看提交历史 |
| `create_gitignore()` | 创建/更新 `.gitignore`，自动同步 `.dpc` 屏蔽规则（已存在时需确认） |

### memory_manager — 跨会话项目记忆
| 工具 | 说明 |
|------|------|
| `write_memory(key, title, content, summary)` | 写入或更新一条记忆，正文存独立文档，标题/摘要存索引 |
| `search_memory(query)` | 按关键词检索 key、标题、摘要与正文 |
| `get_memory(key)` | 按 key 获取记忆的标题、摘要与完整正文 |
| `list_memory()` | 列出全部记忆条目（按更新时间倒序） |
| `delete_memory(key)` | 删除记忆（索引与文档一并删除） |

记忆存放于工作目录的 `Dmemory/` 文件夹（正文为 `{key}.md` 独立文档，索引为 `index.json`），同一项目跨会话共享，并自动加入 `.dpc` 屏蔽规则防止被其他工具误改。

---

## 创建自定义技能

### 文件夹结构

```
skills/
├── my_skill/
│   └── skill.py
├── calculator/
│   └── skill.py
└── web_search/
    └── skill.py
```

### skill.py 模板

```python
skill_info = {
    "name": "my_skill",
    "description": "技能描述",
    "functions": {
        "my_function": {
            "description": "函数描述",
            "parameters": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "参数1"},
                    "param2": {"type": "number", "description": "参数2"}
                },
                "required": ["param1"]
            }
        }
    }
}

def my_function(param1: str, param2: float = 0.0) -> str:
    return f"结果: {param1}, {param2}"
```

### 要求

1. 每个技能一个独立文件夹，名称即技能名
2. 必须包含 `skill.py`
3. `skill_info` 必须定义 `name`、`description`、`functions`
4. 函数参数类型需与 JSON Schema 兼容
5. 文件夹名不能以下划线开头

### SkillContext 注入（推荐）

技能函数可声明 `context` 参数获取统一接口：

```python
def my_function(context, param1: str) -> str:
    # context.work_directory — 当前工作目录
    # context.log_info("消息")     — 日志
    # context.file_operation(...)  — 文件操作
    # context.require_confirmation(...) — 用户确认
    return "结果"
```

未声明 `context` 的函数保持向后兼容。

---

## 工具命名规则

- **Skill**: `skill_<技能名>_<函数名>` → 例：`skill_calculator_calculate`
- **Plugin**: `plugin_<插件名>_<函数名>`
- **MCP**: `mcp_<服务器名>_<工具名>` → 例：`mcp_filesystem_read_file`

---

## MCP 服务器配置

MCP 服务器在 `date/mcp_servers.json` 中配置（与 `models.json` 同级）；首次启动时该文件会自动创建为空白内容（`{"mcpServers": {}}`）。结构如下：

```json
{
  "mcpServers": {
    "filesystem": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/data"],
      "env": { "TOKEN": "${MY_TOKEN}" },
      "enabled": true
    },
    "remote-sse": {
      "transport": "sse",
      "url": "https://example.com/sse",
      "headers": { "Authorization": "Bearer ${REMOTE_TOKEN}" },
      "enabled": true
    },
    "remote-http": {
      "transport": "http",
      "url": "https://example.com/mcp",
      "enabled": true
    }
  }
}
```

- `transport` 取值 `stdio`（本地子进程）/ `sse` / `http`（远程）；缺省时按 `command` 推断为 stdio
- `env` / `headers` 中的 `${VAR}` 从 `.env` 展开，避免明文密钥入库
- 启动时按配置串行建连：连接成功才注册工具；连接失败只告警并跳过，不阻断启动
- 断开启停语义：对远程服务器仅释放我方连接，不影响远端服务；对 stdio 会回收程序自身拉起的子进程

---

## /mcp 命令

`/mcp` 独立于技能与工具管理，用于查看与启停 MCP 服务器：

| 命令 | 说明 |
|------|------|
| `/mcp` | 列出全部 MCP 服务器及状态（已连接 / 连接失败 / 已禁用），Enter 切换启用状态 |

启停只改写 `mcp_servers.json` 的 `enabled` 字段；退出界面后统一建连新启用项、断开已禁用项，
并重建工具列表。`/tools` 中仍会列出已连接的 MCP 工具（模型需要可见）。

### AI 安装与控制工具

除远端工具外，MCP 层还提供四个控制工具（不依赖是否已配置服务器）：

| 工具 | 说明 |
|------|------|
| `mcp_install` | 把一台服务器配置写入 `date/mcp_servers.json`（stdio 传 command/args/env，sse/http 传 url/headers） |
| `mcp_uninstall` | 从 `date/mcp_servers.json` 移除某台服务器；若已连接则同时断开并注销其工具 |
| `mcp_list` | 列出已配置的服务器及状态（传输类型、启用、连接、工具数） |
| `mcp_reload` | 重新读取配置文件：连接新增/新启用项、断开已禁用/已移除项，运行期即时生效 |

配置文件和 `.env` 位于工作目录之外，AI 的文件工具无法直接改写，因此安装/卸载统一走这些工具。
`stdskills/mcp-installer` 标准技能（工具名 `stdskill_mcp-installer`）向模型说明完整的安装、列出与卸载流程。

## user_output 精简显示

工具可通过返回 `user_output` 字段简化终端输出。推荐使用结构化 `parts` 格式，将数据与显示分离：

```python
return {
    "success": True,
    "result": value,
    "user_output": {
        "label": "标签",
        "parts": [
            {"text": "文件名", "style": "default"},
            {"text": "+12", "style": "green"},
            {"text": "-3", "style": "red"}
        ]
    }
}
```

**parts 协议**：
- 每个 part 是 `{"text": "...", "style": "..."}` 或纯字符串
- `style` 可选值：`default`、`green`、`red`、`yellow`、`gray`、`cyan`、`blue`
- 渲染由 `format_user_output_line` 统一负责，skill 不应嵌入 colorama 颜色代码
- 向后兼容：`{"label": "标签", "content": "纯文本"}` 仍然可用，但不含自动着色

返回 `user_output` 时，冗长的工具调用/结果区块自动隐藏，仅显示一行简约标签。

## 命令参考

| 命令 | 说明 |
|------|------|
| `/tools` | 查看所有可用工具 |
| `/skills` | 管理技能启用/禁用 |
| `/mcp` | 查看/启停 MCP 服务器 |
| `/toggle` | 切换单个工具启用状态 |

命令前缀默认为 `/`，可通过 `/set` 修改。

## 故障排除

| 问题 | 排查方向 |
|------|----------|
| 技能未加载 | 检查 `skills/` 目录下文件夹结构和 `skill_info` 定义 |
| 工具调用失败 | 检查工具名称格式、参数是否符合 JSON Schema |
| MCP 连接失败 | 确认 MCP 服务器运行状态和连接参数，查看日志 |
