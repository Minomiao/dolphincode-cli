# Dolphin CLI

基于大语言模型的代码智能体。通过技能、标准技能和插件扩展能力，支持工具调用、对话管理、文件操作与用户交互。

## 快速开始

```bash
pip install -r requirements.txt   # 依赖装入项目 venv/
python main.py
```

首次运行会自动创建 `workplace/` 工作目录、`date/config.json`、`date/models.json` 与 `date/.env`，按提示配置 API 密钥和模型即可开始使用；模型清单与服务地址存放在 `models.json`，密钥全部存放在 `.env`（模型条目通过 `api_key_env` 指向对应变量，内置模型共用 `QUICKAI_API_KEY`，自定义模型各自一一对应），旧版配置中的相应数据会自动迁移并清除。

模型通过 `/model` 切换，也可添加自定义模型。内置 deepseek-v4-flash 与 deepseek-v4-pro 两个模型，前者侧重快速响应，后者侧重高质量输出；已废弃模型启动时会给出警告。

## 基本使用

所有命令共用可配置前缀，默认 `/`，可用 `/set` 修改：

| 命令                                | 作用                       |
| --------------------------------- | ------------------------ |
| `/model` `/workdir` `/language`   | 切换模型与 API 密钥、工作目录、界面语言   |
| `/new` `/load` `/list` `/clear`   | 对话的新建、加载、列表、清空           |
| `/tools` `/skills` `/toggle`      | 查看与开关工具、技能               |
| `/effort fine\|normal\|high`      | AI 思考深度，默认 `fine`，切换后持久化 |
| `/showthinking on\|off`           | 显示/隐藏思考过程                |
| `/set` `/changes` `/help` `/quit` | 设置、处理备份变更、帮助、退出          |

`/effort` 三档对应不同行为约束。`/language` 支持 40 种语言，翻译表首次运行同步到 `date/language/`，可直接编辑自定义。

## 技能与扩展

**内置技能**位于 `skills/`，共 10 个：calculator、file\_reader、file\_manager、git、memory\_manager、powershell\_executor、random\_generator、stdskill\_helper、subagent、web\_search，覆盖数学计算与时间、文件搜索读写、版本控制、跨会话记忆、PowerShell 异步执行、随机数生成、标准技能管理、子任务委派与网络搜索。subagent 将自包含的子任务委派给无头子代理执行，子代理拥有独立上下文，仅回传结论与工具轨迹摘要。

**标准技能**位于 `stdskills/`，遵循 Agent Skills 标准的 SKILL.md / skill.yaml 格式，启动时注册为 `stdskill_<名称>` 工具；同一来源的多个技能聚合为单一 `stdskill_<合集名>` 工具，由 skill 参数选择子技能。stdskill\_helper 提供 `create_skill` 创建、`install_skill` 从外部合集导入、`list_skills` 列出已装技能，安装或创建后自动热加载，下一轮对话即生效，无需重启；项目自带 skill-installer 指南技能。

**插件**位于 `plugins/`，以 ZIP 包形式存放，含 manifest.json 声明技能信息，启动时自动加载。

## 安全机制

- 破坏性操作需确认：`delete_file`、`run_script`
- `.dpc` 文件控制目录访问权限，保护程序数据；`Dmemory/` 记忆库自动纳入屏蔽
- AI 操作被限制在工作目录内，文件修改前自动备份到 `date/backup/`，退出时可选择应用或还原
- `run_script` 内置危险命令黑名单，可疑脚本需人工确认

## 许可证

MIT License
