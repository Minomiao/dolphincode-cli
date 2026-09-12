# Dolphin Features

## Core

- [x] CLI chat interface with streaming output
- [x] Multi-model support with deprecation warning system
- [x] Config separation: `config.json` (non-sensitive) + `.env` (API key, work dir)
- [x] Auto migration of legacy config (api_key → .env)
- [x] Splash screen with pixel-art Dolphin and loading progress bar

## Chat

- [x] Streaming response with real-time typing effect
- [x] Thinking process display (dim text, toggled by `/showthinking`)
- [x] Multi-turn conversation history
- [x] System prompt with workspace context
- [x] Plain text output mode (no markdown, no emoji)
- [x] Tool call iteration loop (initial 30 rounds, extendable +20, hard limit 100)
- [x] Configurable max_tokens, temperature
- [x] Context manager with token budget monitoring (70%/85%/95% thresholds)

## Tool System

- [x] Unified tool execution pipeline: skill / plugin / MCP routing
- [x] `format_tool_result()` recursive JSON formatter for terminal display
- [x] Tool confirmation flow (`_process_tool_confirmation`): USER_INPUT, CONFIRMATION, requires_confirmation
- [x] Async compatibility layer (`_run_async`) for sync/async context bridging in request_manager
- [x] Tool call / result display reorder fix (calls before results)

## User Output (`user_output`)

- [x] Skill tools return `user_output` dict with structured `parts` protocol for clean data/display separation
- [x] Parts format: `{"label": "...", "parts": [{"text": "...", "style": "green"}, ...]}`
- [x] Styles: `default`, `green`, `red`, `yellow`, `gray`, `cyan`, `blue` — rendered centrally by `format_user_output_line`
- [x] Skill code no longer embeds colorama ANSI codes; all terminal coloring unified in rendering layer
- [x] Tools with `user_output` skip verbose tool_calls/tool_result blocks
- [x] Backward compatible: `{"label": "...", "content": "text"}` still supported

### Per Tool Display

| 技能 | 工具 | 显示格式 |
|------|------|---------|
| file_reader | `read_file` | `[Read] --filename` |
| file_reader | `list_directory` | `[Read] --dir\` |
| file_reader | `search_files` | `[Search] --pattern` |
| file_reader | `get_work_directory` | `[Read] dirname` |
| file_manager | `create_file` | `[File Change] filename +N -0` |
| file_manager | `modify_file` | `[File Change] filename +N -N` |
| file_manager | `delete_file` | `[File Change] --filename Delet` (需确认) |
| file_manager | `set_work_directory` | `[Work Place] --path` |
| random_generator | `random_int/float/choice/password` | `[Random] --type (details)` |
| calculator | `calculate` | `[Calculator] expr result` |
| calculator | `get_current_time` | `[Calculator] --time time` |
| git | `git_init/status/diff/add/commit/log/create_gitignore` | `[Git] --action` |
| memory_manager | `write_memory` | `[Memory] --write key` |
| memory_manager | `search_memory` | `[Memory] --search query` |
| memory_manager | `get_memory` | `[Memory] --get key` |
| memory_manager | `list_memory` | `[Memory] --list` |
| memory_manager | `delete_memory` | `[Memory] --delete key` |

## Skills

### file_reader
- [x] `get_work_directory`, `search_files` (max 500 results), `list_directory` (max 1000 files, depth 10), `read_file` (paginated, max 1000 lines)
- [x] Relative path validation via DPC access control

### file_manager
- [x] `set_work_directory` (subdirs only, `..` supported, out-of-bounds → reset)
- [x] `create_file` (max 10MB, 1000 lines), `modify_file` (string replace, 3-level matching), `delete_file` (with confirmation)
- [x] Auto-strip line numbers from AI pasted content

### powershell_executor
- [x] `run_script(script, timeout, wait_time)` — async execution via subprocess
- [x] `check_script(command_id)` — poll background command status/output
- [x] `kill_command(command_id)` — force terminate
- [x] Timeout does NOT kill process; continues in background, pollable
- [x] Process lifecycle managed by `modules/powershell_manager.py`
- [x] Auto-cleanup on exit: `atexit` + signal handling
- [x] UTF-8 encoding, output capped at 50000 chars / 500 lines

### random_generator
- [x] `random_int(min, max)`, `random_float(min, max)`, `random_choice(choices)`, `random_password(length, ...)`

### calculator (sympy)
- [x] `calculate(expression)` — sympy evaluation (+ - * / **, sqrt, sin/cos/tan, log, factorial, pi, e)
- [x] `get_current_time` — current datetime string
- [x] sympy Float → Python float/int conversion for JSON serialization

### web_search
- [x] `search(query, num_results)` — Bing HTML search with ad filtering
- [x] Semantic relevance filtering via ONNX embedding (bge-small-zh-v1.5, cosine similarity)
- [x] Keyword substring matching fallback when embedding model unavailable
- [x] Model auto-download and ONNX conversion on first startup

### git
- [x] `git_init` — initialize repo + auto-generate `.gitignore` synced from `.dpc` restricted rules
- [x] `git_status`, `git_diff` (per-path), `git_log` (max_count)
- [x] `git_add` — skips paths blocked by `.dpc`
- [x] `git_commit` — requires user confirmation, English message
- [x] `create_gitignore` — updates the `.dpc` section in existing `.gitignore`
- [x] Runs only in project root; destructive commands (reset --hard, force push) prohibited

### memory_manager
- [x] Cross-session project memory keyed by `.dpc` dir_id
- [x] `write_memory(key, title, content, summary)` — body stored as standalone `{key}.md`, title/summary in `index.json`
- [x] `search_memory(query)` — matches key/title/summary/body, returns sorted results
- [x] `get_memory(key)`, `list_memory()` (updated_at desc), `delete_memory(key)` (index + doc)
- [x] `Dmemory/` folder auto-hidden and added to `.dpc` restricted rules (incl. subpaths)

## File Operations & Security

- [x] Centralized via `modules/file_operation.py` (create, read, modify, delete)
- [x] Path safety: all operations confined to work directory
- [x] DPC (Dolphin Path Control) file protection for sensitive directories
- [x] Auto-create parent directories on file creation

## Backup System

- [x] Auto-backup before modification (`date/backup/`)
- [x] Per-dialog, per-file deduplication
- [x] Pending changes tracking (`backup_info.json`)
- [x] Quit prompt: apply / revert / skip pending changes
- [x] Rich Table display with color-coded actions (green=create, red=delete, yellow=modify) wrapped in Panel
- [x] Backup cleanup on `clear_history` via `backup_mgr.end_dialog_backup()`

## Conversation Management

- [x] Save / load / list conversations (`date/conversations/`)
- [x] Dialog ID generation (UUID)
- [x] `/clear` resets history and work directory
- [x] `/new` creates new dialog; `/load [name]` loads saved dialog
- [x] Conversation history formatting with color-coded user/AI messages

## Command System

- [x] Configurable command prefix (default `/`)
- [x] All commands: help, set, model, open, clear, new, load, saveas, list, tools, skills, toggle, showthinking, quit
- [x] Fuzzy keyword matching for unknown command suggestions
- [x] Auto-validate and repair `date/commands.json` on startup

## Plugin System

- [x] Plugin loader from ZIP files in `plugins/` directory
- [x] `manifest.json` support with skill_info declaration

## MCP Integration

- [x] MCP protocol manager (`modules/mcp_manager.py`)
- [x] Tool prefix format: `<server>_<tool>`

## Architecture

### Bootstrap (`modules/bootstrap/`)
- [x] `paths.py` — unified absolute path resolution for all data directories
- [x] `constants.py` — centralized global constants (limits, thresholds, built-in model seeds)
- [x] PyInstaller-compatible: `sys.frozen` detection for packaged root resolution

### SkillContext (`modules/loader/skill_context.py`)
- [x] `SkillContext` — unified interface for skill functions (work_dir, logger, file_ops, backup, powershell)
- [x] `create_default_context(work_dir)` factory with default dependencies
- [x] Injection via `inspect.signature` — skills declare `context` param to opt-in; backward compatible

## Logging & Error Handling

- [x] Module-level logging with namespaced loggers (`Dolphin.chat`, `Dolphin.skill_manager`, etc.)
- [x] Log file output with rotation
- [x] SympifyError / ImportError graceful fallback
- [x] JSON decode error handling in tool argument parsing
- [x] Tool execution error wrapping (never crash on bad tool)
- [x] API error handling (invalid key, rate limit, server error — graceful degradation)
- [x] Unsent message rollback on API error
- [x] PowerShell timeout and output truncation with transport cleanup
