# Change Log

## v1.2.3 (2026-09-25)

Unified model registry with a three-level management TUI, multimodal vision support, native tool registration, per-message send/display control, and full i18n coverage.

### Model Registry

+ Consolidate model config into `models.json` with API keys mapped to `.env` variables (`5108999`)
  - Single manifest for builtin and custom models; legacy config.json / custom_models.json migrate automatically
  - Per-model key variables derived from model names; builtins share the default variable
+ Align builtin lineup with the DeepSeek pricing doc (`9055786`)
  - `deepseek-flash` / `deepseek-v4-pro` (1M context, 384K output, vision-capable)
  - Deprecated `deepseek-chat` / `deepseek-reasoner` and the renamed flash entries are no longer seeded
+ Drop tier qualifiers from builtin model descriptions (`05b6d54`)

### Model Management TUI

+ Three-level model settings with add / edit / delete actions (`af15f37`)
  - New `form_nav` field form subsystem shared by add and edit flows
  - Multimodal (y/N) switch for custom models, persisted as `capabilities` (`9055786`)

### Multimodal Vision

+ Add `@"path"` image reference parsing and content parts conversion (`a50800c`)
  - Message-level `_images` field stores local paths; converted to OpenAI parts only at the API boundary
  - Platform-isolated file_id cache keyed by (path, mtime) with base64 fallback
+ Add `read_image` tool with synthetic user message injection (`a50800c`)
  - Tool messages cannot carry images, so successful reads append a synthetic user message converted to parts on the next round
  - Automatic degradation for non-vision models (input warning, plain-text history, tool error)
+ Register `read_image` as a native tool through the skill manager (`bdf3570`)
  - New `register_native_tool()` interface shares the `skill_` prefix, lookup table and dispatch chain with directory skills
  - Tool results with an `images` field generically trigger injection; user_output tags render gray/red labels instead of raw JSON

### Message Internals

+ Add per-message `_send` / `_display` control fields (`eebf9ed`)
  - Send filtering preserves tool pairing integrity; history echo skips hidden messages
  - Synthetic image messages are stored with `display=False` to avoid duplicate echo

### i18n

+ Complete translation key coverage for all 40 languages (`7788042`)

### Testing

+ Add form, i18n, context image-parts, vision, key-nav and native-tool tests (`af15f37`, `7788042`, `a50800c`, `bdf3570`)

---

## v1.2.2 (2026-09-06)

Core services layer decoupling, cooperative generation cancel, load-time tool lookup routing, standard skill packs with hot reload, and a subagent delegation skill.

### Architecture: Core Services Layer

+ Decouple core business logic from the TUI layer (`4687698`)
  - New `modules/core/` package with an event bus (`events.py`) and services: `chat_service`, `config_service`, `conversation_service`, `backup_service`
  - `CLIserver` submodules delegate to services instead of embedding business logic
  - Unit tests for the event bus and all four services
+ Fix: resolve `CONVERSATIONS_DIR` lazily to survive early imports (`435c03a`)
+ Ignore web server module locally (`23e7161`)

### Interruptible Generation

+ Add cooperative generation cancel with true-interrupt semantics (`b792970`)
  - Ctrl+C during generation interrupts the current turn and returns to the prompt; Ctrl+C at the prompt exits
  - Interrupted messages are preserved; partial assistant messages get their structure completed without extra notice
  - Blank line between interrupted output and the next prompt

### Backup Management

+ Fold per-turn file operations into a single net backup record (`d535267`)
  - Multiple operations on the same file within one round merge into one net record
  - create→delete nets to no pending record; works for any number of operations

### Tool Routing

+ Resolve skill tools via load-time lookup table (`3f738be`)
  - Loaders build a `_tool_lookup` map (full tool name → skill name, function name) at load time
  - Unambiguous tool resolution across skill / plugin / standard-skill / MCP loaders

### Standard Skills

+ Merge same-source standard skills into one pack tool with skill enum (`e882845`)
  - Multiple skills from the same source folder register as a single `stdskill_<collection>` tool with a skill enum parameter
  - Single-skill sources still register as standalone tools; skills UI truncates long descriptions
+ Install skill collections preserving layout for pack aggregation (`5da1a0c`)
  - Multi-skill collections install to `stdskills/<collection>/<skill>/`; single skills stay flat
+ Hot-reload standard skills after programmatic install or create (`0d712df`)
  - `reload_skills()` rebuilds state locally and swaps atomically, keeping old state on failure
  - Newly installed or created skills take effect on the next chat turn without restart

### Subagent

+ Add `subagent` skill for delegating self-contained tasks to a headless child agent (`ae93ac0`)
  - Runs via the non-interactive `chat_ai_sync` caller with an independent context
  - Returns a trimmed conclusion and tool trace summary; whitelist limited to file tools to prevent recursion
  - Fix: tool whitelist matching resolves full tool name / skill name / function name via `_tool_lookup` instead of suffix matching

### Testing

+ Add unit tests for events and core services (`4687698`)
+ Add generation cancel and main loop cancel tests (`b792970`)
+ Add backup actions net-record merge tests (`d535267`)
+ Add tool lookup tests (`3f738be`)
+ Add standard skill loader, display, and stdskill helper tests (`e882845`, `5da1a0c`, `0d712df`)
+ Add subagent and ai_caller tests (`ae93ac0`)

---

## v1.2.1 (2026-08-24)

Standard skills (Agent Skills) system, non-interactive chat caller, 400-line module refactoring, robustness fixes, and a growing unit test suite.

### Standard Skills (Agent Skills)

+ Add standard skill loader for SKILL.md based skills (`defa79c`)
  - Recursively scan `stdskills/`, register each skill as a `stdskill_<name>` tool
+ Add `skill-installer` standard skill and track `stdskills/` directory (`6619ea7`)
+ Add `stdskill_helper` native skill and align skill-installer with it (`e53d7b1`)
  - Tools: `create_skill`, `install_skill`, `list_skills`
+ Support `skill.yaml` definitions and align calculator user output (`1de5f15`)
+ Show `[skills]` user output when a standard skill is called (`43f0399`)
+ Add user_output for recovered tool messages in conversation repair (`d92bf29`)
+ Fix: case-insensitive definition file matching in `install_skill` (`725004b`)

### Module Refactoring

+ Split oversized modules to meet the 400-line rule (`ba8daa8`)
  - Extract `backup_actions` from `backup_manager`, `prompt_defaults` from `prompt_manager`, new `registry` and `translations` modules
+ Extract `CommandCacheManager` into `command_cache` module (`2957b93`)
+ Slim down `request_manager` to wired functionality (`3b4d016`)
+ Replace `main_loop` command branches with a dispatch table (`d59dd29`)
+ Unify tool result structure (user_output parts format + success flag) (`e871b56`)
+ Improve `chat_stream` readability (`8acb74a`)

### New Features

+ Add non-interactive `chat_ai` caller with tool whitelist and full result (`ae55c17`)
+ Merge `/load` and `/list` commands into an arrow-key conversation selector (`fbc67ce`)

### Stability & Fixes

+ Fix: handle `CancelledError` race in PowerShell task timeout wait (`ea616a3`)
+ Include stderr in PowerShell command results (`cd8f5e6`)
+ Classify exceptions and add daily log rotation (`32a042d`)
+ Harden `file_operation` against cross-drive and oversized params (`cead656`)
+ Harden `request_manager` thread pool and drop dead callback (`c7b2c04`)
+ Harden skill security against injection and path traversal (`6f763f7`)
+ Remove dead code and fix content search regression (`780b49f`)
+ Fix: `record_change` updates the latest unconfirmed record (`6be6063`)
+ Centralize default model and harden edge cases (`f78d4d8`)

### Testing

+ Add unit tests for core logic modules (`7551683`)
+ Add unit tests for recent robustness fixes (`b0035bc`)
+ Add command cache unit tests and fix `FakeRequestManager` signature (`e2ffb95`)
+ Add web_search unit tests (`172f673`)

### Chore & Docs

+ Permanently ignore `tests/` and build output (`65abf2c`, `7acca49`)
+ Drop unused flask and flask-cors dependencies (`45846be`)
+ Refresh README to reflect the current project state (`a41564f`)

---

## v1.2.0 (2026-08-07)

Multi-language i18n with arrow-key navigation, two new skills (git, memory_manager), jieba-based web search, model management overhaul, and stability fixes.

### Multi-language i18n & Arrow-key Navigation

+ Add multi-language support with `/language` command and arrow-key navigation (`6b76cc6`)
  - 40 languages with built-in translation tables
  - `date/language/{code}.json` generated on first run; file-based translations override built-ins with automatic fallback
+ Add arrow-key navigation for settings UIs with full i18n coverage (`b42679d`)
  - Settings, model, effort, and skills screens navigable via ↑/↓/Enter/Esc
  - Digit fallback for non-interactive (piped) terminals
+ Make system prompt language directive follow the selected display language (`7bf7108`)
+ Keep language list within terminal view; add per-turn language rule to prompt (`564e437`)
+ Keep token usage line on a new line after streaming reply (`be52228`)
+ Rewrite nyannyan translations based on simplified Chinese (`ea02d51`)

### New Skills: memory_manager & git

+ Add `memory_manager` skill for cross-session project memory (`d746937`)
  - Body stored as standalone `{key}.md` documents, title/summary in `Dmemory/index.json`
  - Keyed by `.dpc` dir_id — same work directory shares memory across sessions
  - `Dmemory/` auto-hidden and added to `.dpc` restricted rules (incl. subpaths)
  - Tools: `write_memory`, `search_memory`, `get_memory`, `list_memory`, `delete_memory`
+ Add `git` skill with `.dpc`-aware `.gitignore` generation (`7195bc9`)
  - `create_gitignore` / `git_init` auto-sync `.dpc` restricted rules into `.gitignore`
  - Tools: `git_init`, `git_status`, `git_diff`, `git_add`, `git_commit`, `git_log`, `create_gitignore`
  - `git_add` skips `.dpc`-blocked paths; commits require user confirmation
+ Guide git skill usage and per-turn memory recording in system prompts (`7d1273b`)
+ Remove misleading back hint from control pages — interactive key nav only recognizes single keys (`ac409d9`)
+ Show fold-corner symbol while thinking in hidden-thinking mode (`dceff7b`)

### SkillContext Enhancements

+ Expose DPC restriction management to skills via SkillContext (`822bbe6`)
  - `get_restricted_paths()`, `add_restriction()`, `remove_restriction()`, `filter_allowed_paths()`
+ Expose constants to skills via `context.constants` (`cf53e32`)
+ Fix `list_directory` to honor `.dpc` restrictions on directories (not just files)

### Web Search Refactor

/ Replace embedding model with jieba tokenization for web search (`c7f8ddc`)
  - Remove ONNX embedding pipeline (`model_downloader`, `onnx_converter`, `embedding`)
  - Keyword substring matching as primary relevance filter
+ Expand jieba dictionary to cover 15 technical domains (`7c80469`)
+ Return line numbers and matched content in content search (grep-style) (`5b25cf4`)
+ Prevent redundant model downloads and ONNX conversion failures (`e5ab484`)

### Model Management

+ Remove deprecated models and add custom model management (`c9ec0e2`)
  - Custom model add/remove with per-model settings

### Commands

/ Rename `/open` to `/workdir` and auto-create missing work directory (`c6472b9`)

### Stability & Persistence

+ Fix: make conversation persistence lossless with stream buffer and atomic writes (`7375026`)
+ Resolve five high-risk stability issues (`6da1ac0`)
+ Address medium and low severity stability issues (`8a058ca`)

### Documentation

/ Rebrand to dolphincode and sync docs with actual commands and skills (`09cf9be`)
+ Document git and memory_manager skills in README, FEATURES, and skill guides (`0fa1a9b`)

---

## v1.1.7 (2026-07-22)

CLI module architecture, Rich command interfaces, prompt caching, thinking display refinement, and conversation UX improvements.

### Architecture: CLIserver Module Split

/ Split `main.py` into `modules/CLIserver/` submodules (`245be79`)
  - `main_loop.py` — command parsing and dispatch
  - `callback.py` — chat event callbacks
  - `display.py` — /help, /tools, /skills interfaces
  - `settings.py` — /set, /model interfaces
  - `conversation_ops.py` — /new, /load, /list, /open
  - `changes.py` — pending file changes confirmation
  - `screen_refresh.py` — unified clear/refresh/enter_screen
  - `header.py` — header and history rendering
  - `state.py` — UIState and AppState containers
+ Extract `BaseSkillLoader` from duplicated skill loading logic (`245be79`)
/ Decouple logger from dpc_manager and clean chat imports (`b8c5649`)
+ Add missing logs and performance timing logs (`ab6c1ca`)
/ Unify code style per Dolphin naming conventions (`245be79`)

### Startup Performance

+ Defer heavy module imports to startup progress stages (`4451d10`)
  - OpenAI, chat, conversation_loader loaded after splash screen
  - Progress bar feedback for each import stage
  - Module references stored in `AppState` for lazy access

### Rich Command Interfaces

+ Add independent screen UI for all command interfaces (`3cc3efa`)
  - /help — Rich Panel header + Table of commands + footer prompt
  - /tools — Rich Panel header + Table of available tools + footer prompt
  - /skills — Rich Panel header + interactive toggle Table
  - /set — Rich Panel header + config Table + interactive options
  - /model — Rich Panel header + model selection Table + API key management
  - /list — Rich Panel header + conversation Table with current marker
  - Unified `enter_screen()` → clear → render → restore pattern
+ Show command echo in cyan with dim description after exiting screen (`4ac0aff`)
  - `> /help` in cyan, `╰─显示此帮助信息` in dim gray
  - Consistent visual style across all command exits

### Prompt Management & Caching

/ Migrate system prompts from JSON to individual TXT files with English tag structure (`b133285`)
  - One file per prompt section (identity, tools, guidelines, etc.)
  - English tag names for bilingual content organization
/ Separate static system prompt from per-turn dynamic context for prompt caching (`b06621f`)
  - Static prompt: identity + tools + guidelines (cacheable prefix)
  - Dynamic context: effort level, work directory, skill status (per-turn)
/ Store per-turn context in `_context` field instead of polluting content (`e88696a`)
/ Move dynamic context to last user message and sync back for cache prefix matching (`e368966`)

### Thinking Display Refinement

/ Refine thinking display with fold-corner prefix and on/off toggle (`2b3c327`)
+ Add fold-corner symbol (`╰─`) and indent for response after thinking (`8632a7b`)
  - After thinking ends, first response line indented with fold-corner
  - Subsequent lines aligned with indent for visual grouping
  - Indent cleared on next user message for clean transitions

### Conversation UX

+ Fix: return to main after model selection and preserve messages on client rebuild (`e28c8ba`)
+ Prevent /new from creating duplicate-named conversations (`7926045`)
  - Auto-save current conversation before creating new one
+ Resolve command matching failures caused by prefixed-keyword mismatch (`c57416a`)
/ Remove redundant blank lines between user input and thinking/response output (`89dedfd`)
  - Remove empty line after `>` user input in live callback
  - Remove empty line after `>` user input in history formatting
  - Remove empty line after `response_end`
  - Keep one blank line before each conversation turn for separation

### Confirmation UI

/ Refactor change confirmation UI with Rich components and conversation context (`dccb09e`)
+ Fix scroll and token display timing in confirmation screen (`9a69599`)

### Token Usage & Context

+ Use API-provided token usage instead of estimation (`3a188a0`)
+ Fix create_file backup issue and enhance tool guidance (`896bd47`)

### ONNX Model

/ Persist `onnx_converted` flag before cleaning original weights (`40b1e51`)
  - Prevents repeated conversion attempts on restart

---

## v1.1.6 (2026-07-11)

User Output parts protocol, web search embedding model with ONNX runtime, web page fetching, tool spinner animation, and packaging updates.

### User Output — Structured Parts Protocol

/ Refactor `user_output` from implicit state to structured `parts` protocol
  - Each output line is a list of `{type, content, style}` dicts
  - `format_user_output_line()` formats parts with color-coded rendering
/ Remove implicit state tracking; tool execution flow uses explicit parts pipeline
/ Update FEATURES.md to document the new parts protocol

### Web Search Enhancement

+ Add web page content fetching to `web_search` skill (`c419871`)
  - Fetch full page content from search result URLs
  - Extract readable text from HTML responses
+ Enable `web_search` skill by default (`58cada0`)
/ Overhaul `web_search` with Bing search integration (`5e2a1e2`)
+ Add embedding-based relevance filtering for search results (`93853e2`)
  - Separate embedding encoding (`EmbeddingModel`) from filtering logic
  - Use cosine similarity to rank and filter search snippets

### Embedding Model & ONNX

+ Add `modules/bootstrap/model_downloader.py` — downloads `bge-small-zh-v1.5` from HuggingFace
  - Mirror support for mainland China (`hf-mirror.com`)
  - Download verification via config flag + file existence check
+ Add `modules/bootstrap/onnx_converter.py` — converts safetensors to ONNX format
  - Auto-conversion on first run after model download
  - Config-based state tracking (`onnx_converted` flag)
+ Add `modules/functions/embedding.py` — `EmbeddingModel` singleton for vector encoding
  - ONNX Runtime inference (primary path)
  - SentenceTransformer torch fallback
  - Thread-safe lazy loading

### Thinking Mode

+ Integrate DeepSeek thinking mode with effort level system (`cf3c1b3`)
  - `reasoning_effort` parameter mapped to effort levels
  - Supports `fine`/`normal`/`high` with corresponding reasoning depth

### Tool Execution UX

+ Add tool spinner animation with Braille frames before tool execution (`7098618`)
+ Offload sync skill calls to `asyncio.to_thread` for responsive event loop

### Plugin Fix

+ Add `modules/__init__.py` to fix plugin import resolution (`3dc5a8f`)
  - Repack `user_input_plugin.zip` with corrected import path

### Packaging

+ Add `rich`, `huggingface_hub`, `sentence_transformers`, `onnxruntime`, `transformers`, `torch` to `hidden_imports`
+ Replace `--collect-submodules rich._unicode_data` with `rich` + `huggingface_hub`
+ Add `onnxruntime>=1.18.0`, `huggingface-hub>=0.20.0`, `sentence-transformers>=5.0.0` to `requirements.txt`

### Documentation

/ Simplify README: remove internal architecture details (`317fc98`)
/ Update README with web_search overhaul, embedding model, and Bing search docs (`5e2a1e2`)

---

## v1.1.5 (2026-06-27)

Effort/thinking depth system, PowerShell command cache, security hardening, code quality improvements, and backup management refactor.

### Effort / Thinking Depth System

+ Add `/effort` command with three levels: `fine` (精简), `normal` (标准), `high` (深度)
+ `/effort` without argument displays current level
+ Level persisted to `config.json`, restored on startup
+ Dynamic effort prompts inject behavior constraints into system prompt via `prompt_manager`
+ Chinese label: "思考深度" (replaces "努力程度") throughout all modules and README
/ Rename effort level `medium` → `normal` across all modules, commands, and documentation

### PowerShell Command Cache

+ Add `CommandCacheManager` in `powershell_manager` with TTL-based cache
+ Auto-destroy cache entries after AI reads them (security-first)
+ Memory cache overflow spills to persistent storage (disk)
+ Persistent cache force-deleted on startup (`force_all` cleanup)
+ Cache size limited to 20 entries with `cleanup_expired_persistent()`
+ Cache directory protected by DPC access control

### Security & Robustness

+ Add symlink detection to file path validation — prevents bypass via symbolic links
+ Harden PowerShell dangerous pattern detection against string concatenation and dot-invocation bypasses
+ Use `secrets` module for cryptographically secure random password generation (Issue #14)
/ Sanitize error messages returned to AI/user — keep full traceback in local logs only
/ Replace broad `except Exception` handlers with specific exception types (Issue #2)

### Code Quality

/ Refactor `main.py` global variables into `state` container objects (Issue #1)
+ Add type annotations for public interfaces across modules (Issue #7)
/ Extract hardcoded magic numbers in conversation recovery to constants (Issue #6)
/ Fix inconsistent logging levels and refactor thinking log (Issue #8)

### Backup Management Refactor

/ Store backups inside conversation folders with unified `backup_registry.json`
/ Remove in-memory backup cache — eliminates cross-conversation conflicts
/ Use `dialog_id = conv_id` (unified identifier)
/ Simplify folder structure (file_id based, no dialog_id layering)

### System Prompt & Dev Mode

/ Refactor system prompt management with centralized `prompt_manager`
+ Add dev mode trigger for testing/development

### Task Timeout & Validation

+ Add task timeout protection and background process auto-cleanup (Issue #12)
+ Add input validation for `max_tokens` range and `command_prefix` length in `/set` mode (Issue #11)

### Config & Defaults

/ Separate config read/write concerns: extract `ensure_config()` from `load_config()`
/ Raise default `max_tokens` from 8192 to 18000

### Circular Dependency

/ Resolve circular dependency: move safe lazy imports to top level (Issue #13)

### Confirmation UX

+ Auto-refresh screen after confirmed operation completes to clear confirmation dialog

### Documentation

/ Update README with `/effort` command and thinking depth system documentation

---

## v1.1.4 (2026-06-21)

Bootstrap module, SkillContext architecture, rich Table for pending changes, async compatibility layer, and UI polish.

### Architecture: Bootstrap Module

+ Add `modules/bootstrap/` with `paths.py` and `constants.py` for centralized path and constant management
+ `paths.py` — compute absolute paths from project root (PyInstaller-compatible)
+ `constants.py` — unify all global constants (file limits, thresholds, MODEL_REGISTRY, etc.)
+ Eliminate hardcoded relative paths — all paths now resolved from `PROJECT_ROOT`
+ `BACKUP_DIR` upgraded from relative to absolute path via bootstrap

### Architecture: SkillContext

+ Add `SkillContext` (`modules/loader/skill_context.py`) — unified injection interface for skill functions
+ `create_default_context(work_dir)` factory with all dependencies wired (logger, request_manager, backup, powershell)
+ Skills declare `context` parameter to receive context; backward-compatible via `inspect.signature`
+ Rewrite 3 core skills to use `context`: powershell_executor, file_reader, file_manager
+ Remove 11 duplicated helper functions across skills
+ Remove 9 `sys.path.insert` hacks from skills
+ Fix SkillContext to always use config work_directory instead of `os.getcwd()` fallback

### Rich CLI: Pending Changes Display

/ Replace plain-text pending changes output with `rich.Table`
+ Color-coded actions: **创建** (green), **删除** (red), **修改** (yellow)
+ Wrap summary + table in `rich.Panel` with cyan border
+ Simplify display: only count, action type, and file path (remove timestamp/dialog_id)

### Async Compatibility & Tool Unification

+ Add async compatibility layer (`_run_async`) for sync/async context bridging in request_manager
+ Unify tool execution pipeline across skill / plugin / MCP routing paths

### Screen Refresh & Conversation Display

+ Unify screen refresh logic across conversation management
+ Standardize conversation history formatting with color-coded messages

### UI Polish

+ Left-align Dolphin splash art for cleaner layout
+ Progress bar percentage displayed in blue

### Documentation

+ Update README.md, FEATURES.md, SKILL_OPERATION_GUIDE.md to reflect current architecture
+ Document bootstrap module and SkillContext patterns

---

## v1.1.3 (2026-06-14)

Rich CLI styling, showthinking history rerender, model settings UX, code refactoring, and architecture improvements.

### Architecture: Bootstrap Module

+ Add `modules/bootstrap/` with `paths.py` and `constants.py` for centralized path and constant management
+ `paths.py` — compute absolute paths from project root (PyInstaller-compatible)
+ `constants.py` — unify all global constants (file limits, thresholds, MODEL_REGISTRY, etc.)
+ `__init__.py` — `bootstrap.init(root)` called by `main.py` at startup
+ Eliminate hardcoded relative paths (`"date/"`, `"workplace"`) — all paths now resolved from `PROJECT_ROOT`
+ `BACKUP_DIR` upgraded from relative `"date/backup"` to absolute path via bootstrap
+ `powershell_manager` moved from `modules/loader/` to `modules/functions/`

### Architecture: SkillContext

+ Add `SkillContext` (`modules/loader/skill_context.py`) — unified injection interface for skill functions
+ `create_default_context(work_dir)` factory with all dependencies wired (logger, request_manager, backup, powershell)
+ Skill functions declare `context` parameter to receive context; backward-compatible (`inspect.signature` detection)
+ Rewrite 3 core skills to use `context`:
  - `powershell_executor` — `context.require_confirmation()`, `context.execute_script()`, etc.
  - `file_reader` — `context.work_directory` replaces `get_work_dir()`, `_is_path_allowed` now receives work_dir as param
  - `file_manager` — `context.file_operation(...)` replaces manual `req_mgr.create_file_operation_request()` chain
+ Remove 11 duplicated helper functions across skills (`get_logger`, `get_work_dir`, `get_request_manager`, `get_backup_manager`)
+ Remove 9 `sys.path.insert` hacks from skills
+ `SkillManager` and `PluginSkillLoader` `call_tool` now inject `SkillContext`

### Rich CLI Integration

+ Add `rich` library dependency for modern terminal formatting
+ Replace plain-text header with `Panel` (rounded border, dim text, bright-blue dolphin art)
+ Replace `_progress_bar()` with live-updating `Progress` bar (dim unfilled, cyan filled)
+ Remove emojis from CLI output per project convention

### Show Thinking Improvements

+ Toggling `/showthinking on|off` now clears screen and rerenders full conversation history
+ Existing thinking blocks in history are immediately shown or hidden based on new setting

### Model Settings UX

+ Reorder model selection before API key input for more intuitive flow
+ Simplify model settings UI by removing redundant prompts

### Code Refactoring

/ Replace lengthy if-else chains with `match`/`case` and dispatch tables in `chat.py`
/ Remove redundant work directory status messages in `open_work_directory`

## v1.1.2 (2026-06-07)

Context manager with token budget monitoring, API error resilience, string-based file modify, and /new improvements.

### Context Manager — Token Budget Monitoring

+ Add `ContextManager` (`modules/chater/context.py`) for message assembly and token estimation
+ Three warning thresholds: 70% (info), 85% (warning), 95% (critical) of context window
+ Unify 4 message splicing points in chat.py into `context.prepare_messages()`
+ Add `_check_context_usage()` callback after each chat round for real-time budget awareness
+ Add `context_window` field to `MODEL_REGISTRY` (1M for v4 models, 128K for legacy)
+ Add `config.get_context_window()` as single source of truth

### API Error Resilience

+ Catch API errors (invalid key, rate limit, server error) to prevent crash
+ Rollback unsent user message on API error to prevent chat history loss
+ Save tool results to conversation data before displaying to user (prevents lost context on crash)

### File Operations Refactor

/ `modify_file`: changed from start/end line range to `old_str`/`new_str` string replace
/ Add 3-level matching for `modify_file`: exact → whitespace-stripped → fuzzy (95% threshold)
/ Remove line number annotations from `read_file` output completely
/ Increase limits: `read_file` 400→1000 lines, `create_file` 500→1000 lines (100-line redundancy)

### /new Command Improvements

+ Support `/new <name>` with inline name argument to create named conversation directly
+ Add screen clear on new conversation creation for cleaner UX

## v1.1.1 (2026-05-31)

PowerShell dangerous command detection with auto-execute/confirm split, conversation repair for interrupted tool calls, smart line numbering in file_reader, and output field unification.

### PowerShell Dangerous Command Detection

+ Add `_is_dangerous_script()` with ~60 regex patterns covering 7 threat categories:
  - Filesystem destruction: `remove-item`, `rm`, `del`, `format c:`, `diskpart`
  - Process/service control: `stop-process`, `taskkill`, hidden `start-process`
  - System state changes: `shutdown`, `bcdedit`, `netsh firewall`, `set-executionpolicy`
  - Registry modification: `reg add/delete`, `regsvr32`, `set-itemproperty` on registry paths
  - User/permission operations: `new-localuser`, `icacls`, `takeown`, `attrib +h`
  - Scheduled tasks/persistence: `schtasks`, `wmic startup`, `sc create/delete`
  - Code execution/download: `invoke-expression`, `iex`, `Net.WebClient`, `mshta`, `certutil`, `rundll32`, Base64 decode-execute chains
+ Split `run_script()` into two paths based on danger detection:
  - **Safe commands** → `auto_execute: True`, direct execution without user prompt
  - **Dangerous commands** → `requires_confirmation: True`, full script preview (≤500 chars) shown to user
+ Add `auto_execute` fast path in `_process_tool_confirmation()` bypassing confirmation for safe scripts
+ Safe scripts use compact `short_preview` (first line, ≤80 chars) in user_output
+ All detection patterns are lowercase for case-insensitive matching against lowercased input

### Conversation Repair

+ Add `repair_conversation_messages()` to auto-complete missing tool call results after crash/interruption
+ Auto-complete file tools (`create_file`, `read_file`, `modify_file`, `delete_file`) by reading actual disk state
+ Generate interrupt notification for non-file tools indicating result was lost
+ Mark repaired entries with `_recovered: True` so AI can distinguish from real results
+ Conversation loader calls repair on every load with repair count logging

### Smart Line Numbering

/ Change `read_file()` line number display: every-line → only when file exceeds 100 lines
/ When enabled, annotate first line and every 20th line (20, 40, 60...) with `N|` prefix
/ Files ≤100 lines: no line numbers at all, clean output
+ Update `line_number_format` description to reflect new behavior

### PowerShell Manager Improvements

/ Rename response field `stdout` → `output` for consistent field naming across all result types
+ Add `_completed_outputs` dict to retain output after process exits (prevent lost output on re-query)
+ `check_script()` and `kill_command()` now return cached output if command already completed
/ Fix `request_manager` missing `user_output` extraction in `requires_confirmation` request handling
+ Ensure `output` field present in all error results for uniform response shape

### UI

/ Change thinking time display from `思考完成(1s)` to `思考完成1s` (remove parentheses, cleaner look)

## v1.1.0 (2026-05-24)

File protection via DPC access control, improved work directory switching, hidden DPC files, and build script.

### DPC Access Control

+ Add `restricted` field to `.dpc` format for path-level access control (default `[".dpc"]`)
+ Add `is_path_allowed()`, `filter_allowed_paths()`, `ensure_restriction()` to dpc_manager
+ Logger auto-creates `date/.dpc` with `restricted: ["*"]` on first init (protects all program data)
+ file_reader and file_operation check dpc restrictions before reading/writing/listing/searching
+ list_directory and search_files filter out restricted files from results
+ DPC check walks up directory tree to find nearest `.dpc` for restriction rules

### Work Directory

+ Clear screen and refresh conversation display when switching work directories
+ Auto-save old conversation before switching to new work directory
+ Fallback to default `workplace` directory when configured directory no longer exists
+ Create empty conversation data file automatically when `.dpc` references missing conversation

### Hidden DPC Files

+ Set `.dpc` file as hidden on Windows using `SetFileAttributesW` API
+ Properly restore/remove hidden attribute before writing to avoid permission errors
+ Preserve existing file attributes when toggling hidden flag

### Build

+ Add `package.py` build script using PyInstaller `--onedir` (not `--onefile`)
+ Add `pyinstaller>=6.0.0` to requirements.txt

## v1.0.0 (2026-05-06)

User Output System, extendable tool iterations, sympy calculator, async PowerShell manager, splash screen, and CMD-friendly UI overhaul.

### User Output System

+ Add `user_output` mechanism for skill tools with compact terminal display (label + content)
+ Add colored label/output separation (colorama Fore/RED, Fore/GREEN, Fore/LIGHTBLACK_EX)
+ Implement per-tool user_output display for all 6 skills
  - file_reader: `[Read]`, `[Search]` labels
  - file_manager: `[File Change] +N/-N`, `[Work Place]`, `Delete` with color
  - random_generator: `[Random]` with gray parameter hints
  - calculator: `[Calculator] expr(result) result`
  - powershell_executor: `[PowerShell]` with status and output
+ Add user_output for plugin USER_INPUT/CONFIRMATION requests, hiding verbose tool_call/tool_result blocks
+ Fix tool_calls/tool_result display order (calls before results)
+ Add confirmation protection for delete_file with system-level confirm flow
+ Add missing user_output to all skill error paths

### Tool Iteration

/ Increase max tool call iterations from 20 to extendable system (initial 30, +20 on confirm, hard limit 100)
+ Add interactive confirmation prompt when iteration limit reached
+ Fix iteration counter to include first API call round

### Calculator

/ Replace basic arithmetic calculator with sympy-powered expression evaluator
+ Support: + - * / **, sqrt, sin/cos/tan, log, factorial, pi, e
/ Fix sympy Float → Python float/int JSON serialization

### PowerShell Executor

/ Extract subprocess management into dedicated `modules/powershell_manager.py`
+ Support `run_script`, `check_script`, `kill_command` with async execution
+ Implement `wait_time` mechanism: immediate return on completion, background polling on timeout
+ Timeout does not kill process — continues in background with command_id tracking
+ Auto-cleanup on exit via atexit + signal (SIGINT/SIGTERM)
+ Transport leak prevention with `_DummySock` pattern
+ UTF-8 output encoding, output capped at 50000 chars / 500 lines

### UI & Terminal

+ Add pixel-art DOLPHIN splash screen with loading progress bar
+ Add alternate screen buffer for `/set`, `/skills`, `/model` modes
/ Change thinking label from DIM to LIGHTBLACK_EX for legacy CMD compatibility
+ Add `/showthinking` command to toggle thinking process display (on/off)
+ Add fuzzy keyword matching for unknown command suggestions
- Remove all emoji from terminal prompts, use yellow colored brackets instead
+ System prompt enforces plain text output (no markdown, no emoji)

### Command System

/ Refactor command system: prefix-based routing, startup auto-validation
+ Intercept unknown commands with fuzzy match suggestions instead of sending to AI
+ Add `_get_default_commands()` as single source of truth, auto-repair on startup

### Config

/ Separate sensitive data into `date/.env` (API key, work directory)
/ Strip api_key and work_directory from config.json permanently
+ Auto-migration of legacy config (api_key + work_directory → .env)

### Documentation

+ Create FEATURES.md with bilingual descriptions (English + Chinese)
/ Update README.md to match actual code structure, commands, and architecture
+ Add architecture descriptions: powershell_manager, request types, config keys

### Code Quality

/ Simplify read_file output format with `N|` line numbering and English annotations
/ Clean up file_manager dead code (removed unused functions)

### Plugin

+ Re-packaged user_input_plugin.zip for consistency

### Validation

+ Add pre-send validation for model and API key before sending message to AI
+ Missing config shows red error with `/model` command hint and DeepSeek registration guide
+ Message blocked from reaching AI when config is incomplete

## v0.2.2-fix (2026-04-26)

+ Add path traversal protection for file operations (create, read, modify, delete)
/ Change thinking text color from Style.DIM to Fore.LIGHTBLACK_EX for legacy CMD compatibility
/ Keep "思考过程:" label in default color, only think content and delimiter in gray
/ Increase max tool call iterations from 10 to 20
+ Add /open command to switch work directory independently from /set settings mode
/ Extract work directory setting from settings_mode into standalone open_work_directory()
+ Support /open with path argument (direct switch) and without (interactive prompt)
/ Improve load_commands() to merge file commands onto defaults instead of replacing
+ Add _get_default_commands() as single source of truth for built-in commands
/ Fix cached commands.json blocking new commands added in code updates
/ Update README to reflect /open command and revised work directory configuration flow

**modules/file_operation.py**:
  / Add relative_to(work_path) validation to relative path branches in all 4 methods
  / Reject paths that resolve outside work_directory with clear error message

**main.py**:
  + Add open_work_directory(path) function with interactive fallback and skill reload
  + Add /open command handler in main loop with argument parsing
  / Remove work directory display, input, save, and reload from settings_mode
  / Change thinking callbacks (thinking, thinking_start, thinking_chunk, thinking_end) to Fore.LIGHTBLACK_EX

**modules/commands.py**:
  + Add open command definition (/open → "打开/切换工作目录")
  / Refactor load_commands() to use _get_default_commands() as base and merge file data
  / Prevent new commands from being hidden by stale cached commands.json

**modules/chat.py**:
  / Change max_iterations from 10 to 20

**README.md**:
  / Add /open command to command list table
  / Update /set description to remove work directory reference
  / Update work directory section to reference /open instead of /set
  / Add /open to execution flow diagram

## v0.2.1 (2026-04-25)

+ Implement real-time streaming output for AI response content with typewriter effect in terminal
/ Separate thinking and response output to prevent interleaving in terminal display
+ Add new v4 models (deepseek-v4-flash, deepseek-v4-pro) with model registry system
+ Add deprecation tracking for legacy models (deepseek-chat/reasoner/coder → 2026-07-24)
+ Add deprecation warning on startup and in settings mode with remaining days countdown
+ Implement dual-layer work directory system (persisted config + AI temporary variable)
+ Make AI work directory actually switchable via set_work_directory with bounds validation
+ Support relative path navigation (..) to return to parent directory within work root
+ Auto-fallback to root work directory when path goes out of bounds instead of error
+ Keep AI work directory across messages within same conversation session
+ Extract _process_stream() common method to deduplicate ~110 lines of stream loops
+ Extract _process_tool_confirmation() to deduplicate ~360 lines of confirmation logic
+ Extract _execute_powershell_script() to centralize PowerShell execution with timeouts
+ Clean up RequestManager: remove 4 dead handler methods and unused create_request_output
/ Update settings mode model selection to dynamic listing from model registry
/ Change default model from deepseek-chat to deepseek-v4-flash across all modules
/ Reset work directory only on /clear, /new, /load and startup, not every message
/ Rewrite README with quick start first, complete execution flow, and confirmation workflow
/ Reduce chat.py from 989 lines to 691 lines through method extraction

**modules/chat.py**:
  / Refactor stream processing into _process_stream() shared method
  + Add _process_tool_confirmation() for unified USER_INPUT/CONFIRMATION/SKILL_CONFIRMATION handling
  + Add _execute_powershell_script() for centralized PowerShell script execution
  / Remove dead code related to RequestManager pending_requests iteration
  / Remove reset_work_directory() calls from chat() and chat_stream() (mid-conversation)
  / Add reset_work_directory() calls to clear_history() and load_conversation()

**modules/config.py**:
  + Add MODEL_REGISTRY with 5 models, deprecation metadata, and replacement mapping
  + Add get_available_models() to return model list for dynamic UI generation
  + Add check_model_deprecation() with days-left calculation and warning message
  / Update default model from deepseek-chat to deepseek-v4-flash

**modules/request_manager.py**:
  + Add _ai_work_directory module-level variable for AI temporary directory
  + Add set/get/reset_ai_work_directory() and get_persisted_work_directory() functions
  / Modify _handle_config_request('load') to overlay AI work directory on config result
  - Remove _handle_user_input_request, _handle_confirmation_request (dead code)
  - Remove _handle_skill_confirmation, _handle_console_output (dead code)
  - Remove create_request_output (unused)

**skills/file_manager/skill.py**:
  / Fix set_work_directory to use persisted directory as base, AI current as relative resolver
  + Add out-of-bounds auto-fallback to root directory instead of returning error
  + Add from pathlib import Path (previously missing import)

**main.py**:
  / Rewrite settings_mode model selection to dynamic registry-based listing
  + Add deprecated model section with unified deprecation message
  + Add deprecation check on program startup with colored warning
  / Update response output from batch to streaming (response_chunk + response_end events)
  / Add thinking_end before response starts to prevent interleaving
  / Update callback with response_chunk and response_end event handlers

**README.md**:
  / Restructure with quick start at top, complete execution flow documentation
  + Add model list with deprecation dates
  + Add work directory dual-layer mechanism documentation
  + Add confirmation operation flow documentation with extracted method details
  + Add streaming output section
  / Update architecture to reflect cleaned-up module responsibilities

## v0.2.0-alpha (2026-04-22)

+ Implement request manager for skills and plugins
+ Add file operation module for centralized file operations
+ Implement prompt manager module for centralized system prompt management
+ Implement dialog-level backup management with single backup per file per conversation
/ Update file reader and file operation to use consistent line numbering
/ Improve work directory management: temporary switching, reset on new conversation, and clear subfolder usage instructions
+ Enhance request manager with console output support
/ Update README with architecture documentation and command reference
- Remove confirm_action function from user_input plugin
- Remove package_plugin.py build script
- Remove web-related files (main_server.py and Web-electron)
- Remove unused quickai_chat.py and quickai_client.py files

**modules/request_manager.py**:
  + Create new module for managing skill and plugin requests
  + Implement console output support
  + Provide centralized request handling

**modules/file_operation.py**:
  + Create new module for centralized file operations
  + Update skills to use request manager for file operations

**modules/prompt_manager.py**:
  + Create new module for centralized system prompt management

**modules/backup_manager.py**:
  + Implement dialog-level backup management
  + Support single backup per file per conversation

**skills/file_manager/skill.py**:
  / Update to use consistent line numbering
  / Improve work directory management

**plugins/user_input_plugin/**:
  - Remove confirm_action function

**README.md**:
  / Update with architecture documentation and command reference

/ Improve system architecture with centralized management modules
/ Enhance file operation consistency across skills
/ Simplify codebase by removing unused files
/ Improve work directory management and backup organization

## v0.1.4-alpha (2026-04-12)

+ Add async callback support for better web compatibility
/ Restrict work directory to subdirectories only
+ Add colorama library for terminal output coloring
/ Improve output readability with color coding
/ Modify main program to use async main function

**modules/chat.py**:
  + Implement async callback mechanism
  + Add _call_callback method to support both sync and async callbacks
  + Modify chat and chat_stream methods to async
  + Update tool execution to use async calls

**skills/file_manager/skill.py**:
  / Restrict work directory to subdirectories only
  / Default to relative path resolution
  + Add path format hints for AI
  / Remove confirmation requirement for directory changes

**main.py**:
  + Add colorama library integration
  + Implement async main function
  / Add color coding for different output types
  + Initialize colorama for cross-platform support

**requirements.txt**:
  + Add colorama>=0.4.6 dependency

/ Improve terminal output readability with color coding
/ Enhance web compatibility with async callbacks
/ Strengthen security by restricting work directory scope

## v0.1.3-alpha (2026-04-06)

+ Add plugin skill loader functionality
+ Create user input plugin for requesting user information
/ Modify main program to support plugin skills
+ Implement manifest.json based skill information loading
+ Add prompt directory and prompts.json for skill prompts

**modules/plugin_skill_loader.py**:
  + Create new module for loading plugin skills from ZIP files
  + Implement manifest.json parsing
  + Support skill information loading from manifest.json
  + Add error handling and logging

**modules/chat.py**:
  + Integrate plugin skill loader
  + Add plugin tools to available tools list
  + Support plugin skill calls

**main.py**:
  + Add plugin skill management
  + Support enabling/disabling plugin skills
  + Display plugin skills in skill list

**plugins/user_input_plugin/**:
  + Create user input plugin
  + Implement request_user_input function
  + Implement confirm_action function
  + Add manifest.json for skill information
  + Add prompt/prompts.json for skill prompts

/ Improve plugin architecture, separate skill info from code
+ Support plugin skill discovery and loading
/ Enhance system extensibility through plugins

## v0.1.2-alpha (2026-03-30)

/ Refactor PowerShell executor confirmation mechanism to use standard confirmation flow
+ Improve skill operation guide documentation, add backup manager usage instructions
/ Optimize main program confirmation handling logic, support confirmed parameter passing

**skills/powershell_executor/skill.py**:
  + Add `confirmed` parameter to support execution after confirmation
  / Return confirmation request on first call, execute script after confirmation
  - Remove direct print() and input() calls
  + Keep complete script content in logs

**modules/chat.py**:
  + Add confirmed parameter in all three confirmation handling locations
  + Re-call skill to execute actual operation after user confirmation
  / Optimize confirmation handling process

**skills/SKILL_OPERATION_GUIDE.md**:
  + Add backup manager usage guide
  + Provide detailed code examples and usage instructions
  + Expand document structure

/ Unify confirmation mechanism design, consistent with other skills
+ Support confirmation flow for web version
/ Avoid code duplication, improve maintainability
/ Improve logging, enhance system traceability

## v0.1.1-alpha

/ Fix parameter truncation issue, increase max_tokens setting
/ Improve error handling, provide clearer error messages
/ Increase tool call iteration limit

## v0.1.0-alpha

+ Initial version release
+ Implement basic chat functionality
+ Integrate PowerShell executor skill
+ Add file management functionality
+ Implement backup mechanism