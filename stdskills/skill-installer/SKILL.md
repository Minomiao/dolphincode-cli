---
name: skill-installer
description: 当用户要求安装、下载、导入或创建一个新的标准技能<Agent Skills / SKILL.md 格式>到项目的 stdskills 目录时使用。也适用于从技能合集<如 GitHub 仓库、Codex 技能目录>中挑选并放置技能的场景。
---

# 技能安装与创建指南

本项目使用标准 Agent Skills 格式<SKILL.md>，技能统一存放在**项目根目录下的 `stdskills/` 文件夹**中。
本技能指导如何把一个新技能放到 `stdskills/`，或在这里直接创建新技能。

## 核心规则<所有技能必须遵守>

1. **目录**：每个技能一个文件夹，路径为 `stdskills/<技能名>/`
2. **入口文件**：`SKILL.md`，必须以 YAML frontmatter 开头<以 `---` 包裹>，其中必须包含：
   - `name`：小写字母、数字、连字符<`[a-z0-9-]`>，**不允许下划线或空格**；建议与文件夹名一致
   - `description`：一句话说明**何时使用**该技能<这是模型决定是否调用的唯一依据>
3. **命名唯一**：`stdskills/` 内技能名<frontmatter `name`>不得重复，重复会被加载器跳过并在日志中警告
4. **生效时机**：加载器在程序启动时扫描，**新技能需重启 Dolphin 后才注册为工具**<工具名为 `stdskill_<name>`>
5. **不得破坏他人**：不要修改、删除 `stdskills/` 中已有的其他技能

## 方式一：下载技能到 stdskills

适用场景：从 GitHub、技能合集仓库、或本地 Codex 技能目录<`~/.codex/skills/`>获取现成技能。

### 步骤

1. **定位技能**：在来源中找到含 `SKILL.md` 的技能文件夹。常见来源：
   - GitHub 技能合集仓库<如 `anthropics/skills`、各种 agent-skill 市场>，技能通常在 `skills/<技能名>/SKILL.md`
   - 本地 Codex：`~/.codex/skills/<技能名>/SKILL.md`
   - 任意"整包"合集<如下载解压后的 `xxx-main/` 仓库>，其下每个子技能在 `skills/<技能名>/SKILL.md`
2. **下载/解压到临时位置**<如 `beta/` 或系统临时目录>，不要直接下载进 `stdskills/`
3. **只复制技能文件夹本体**：将 `skills/<技能名>`<即 `SKILL.md` + 可选的 `scripts/`、`assets/`、`references/`、`reference/` 子目录>复制为 `stdskills/<技能名>/`
4. **丢弃仓库脚手架**：不要复制 `.git/`、`.github/`、`.claude-plugin/`、仓库根 `README.md`、`LICENSE`、`skill.sh`、构建脚本、展示素材<`assets/` 仅当技能自身需要时才保留>等
5. **校验**<见下方"校验清单">

## 方式二：创建新技能到 stdskills

适用场景：用户想要一个全新的能力，现有技能无法覆盖。

### 最小结构

```
stdskills/<技能名>/
└── SKILL.md
```

### SKILL.md 模板

```markdown
---
name: my-skill
description: 一句话说明何时使用该技能，包含触发场景与适用任务类型。
---

# 技能说明

为模型提供逐步操作指南：
- 触发条件：何时使用、何时不使用
- 执行步骤：Step 1 / Step 2 ...
- 注意事项与最佳实践
- 若需要脚本，写明如何运行<见下方"脚本说明">
```

### 命名与描述建议

- `name` 用连字符分词<如 `file-organizer`>，简短描述能力
- `description` 采用"当用户需要……时使用"句式，明确触发场景；不要描述实现细节

### 如何写好 SKILL.md 正文<提示词质量准则>

正文就是写给模型看的提示词，质量直接决定技能效果。参考本机 `beta/` 下的提示词案例提炼：

1. **具体胜过笼统** — 每条指令都要可执行：
   - Correct: "用 file_manager 列出目标目录所有文件，按修改时间倒序"
   - Incorrect: "查看文件"
2. **给出可执行步骤** — 用编号步骤描述过程，而不是只下结论：
   - Correct: "1. 读取目标文件 → 2. 检查关键字段 → 3. 汇总为表格"
   - Incorrect: "分析代码并给出反馈"
3. **明确输出格式** — 说明结果的结构与呈现方式<分节、表格、`[skills]` 标签等>
4. **覆盖边界情况** — 写明异常场景的处理：无结果、权限不足、目录不存在、输入过大等
5. **质量标准可度量** — 定义"好"的标准<如"每个发现都含 文件:行号 引用">
6. **第二人称直呼模型** — 用"你需要…"，不要"本技能将…"
7. **描述用动词触发** — frontmatter 的 `description` 用动词<开始/运行/构建/测试/生成…>，因为这是模型决定是否调用该技能的扫描依据
8. **写完自测** — 仅凭正文，一个没看过当前对话的模型能否独立完成任务？

### 可选子目录

| 目录 | 用途 |
|---|---|
| `scripts/` | 可执行脚本，供模型用 `powershell_executor` 的 `run_script` 运行 |
| `assets/` | 技能所需的静态资源 |
| `references/` 或 `reference/` | 补充文档，正文中引用 |

## 校验清单<下载或创建后必须执行>

- [ ] `stdskills/<技能名>/SKILL.md` 存在，且以 `---` 开头
- [ ] frontmatter 含 `name`<`[a-z0-9-]`>和 `description`
- [ ] `stdskills/` 中无同名技能<frontmatter `name` 不重复>
- [ ] 未带入仓库脚手架<`.git`、`.github`、`.claude-plugin`、仓库 README 等>
- [ ] 已告知用户：新技能需重启 Dolphin 后生效，工具名为 `stdskill_<技能名>`

## 示例

以创建一个"批量重命名文件"技能为例：

```
stdskills/file-organizer/
└── SKILL.md

# SKILL.md 内容
---
name: file-organizer
description: 当用户需要按规则批量重命名或整理文件夹中的文件时使用。
---

# 文件整理

1. 用 file_manager 列出目标目录所有文件
2. 与用户确认重命名规则<前缀、编号、扩展名分组等>
3. 逐文件执行重命名，完成后用 [skills] 标签输出结果摘要
```

## 参考资料<仅本机，`beta/` 不入库>

编写提示词时可参考本机 `beta/` 下的案例与教程：

- `beta/system-prompt-design.md` — 系统提示词设计模式完整指南<核心结构、4 类 Agent 模式、写法规范、常见坑、长度与测试建议>
- `beta/system-prompts/system-prompt-writing-subagent-prompts.md` — 委派类提示词的写法要点
- `beta/system-prompts/skill-run-skill-template.md` — 具体技能模板示例<含 description 动词建议>
- `beta/system-prompts/` 下的 `system-prompt-*`、`agent-prompt-*`、`skill-*` 等数百个真实案例可对照学习

注意：`beta/` 已被 gitignore，其他机器上可能不存在，引用前先确认路径存在；本技能正文中的准则已自包含，不依赖这些文件。
