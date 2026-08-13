---
name: skill-installer
description: Use when the user asks to install, download, import, or create a new standard skill (Agent Skills / SKILL.md format) into the project's stdskills directory. Also applies when picking skills from a collection (e.g., a GitHub repository or the local Codex skills directory). Prefer performing creation and installation programmatically via the skill_stdskill_helper tools.
---

# Skill Installation and Creation Guide

This project uses the standard Agent Skills format (SKILL.md). Skills live in the **`stdskills/` folder at the project root**. This skill explains how to install or create a standard skill under `stdskills/`. **All file operations are performed by the `skill_stdskill_helper` tools; do not manually read or write `stdskills/` with file_manager.** The tools handle validation, deduplication, and scaffold cleanup.

## Core Rules (mandatory for every skill)

1. **Directory**: one folder per skill at `stdskills/<skill-name>/`
2. **Entry file**: `SKILL.md` must start with a YAML frontmatter (wrapped in `---`) containing:
   - `name`: lowercase letters, digits, hyphens (`[a-z0-9-]`); **no underscores or spaces**; prefer matching the folder name
   - `description`: one sentence explaining **when to use** the skill (this is the only signal the model uses to decide whether to call it)
3. **Unique names**: skill names (frontmatter `name`) must not repeat inside `stdskills/`; duplicates are skipped
4. **Activation**: the loader scans at startup; **a new skill registers as a tool (named `stdskill_<name>`) only after Dolphin restarts**
5. **Do not break others**: never modify or delete existing skills under `stdskills/`

## Option 1: Install an external skill

Applies when fetching a ready-made skill from GitHub, a skill collection repository, or the local Codex skills directory (`~/.codex/skills/`).

### Steps

1. **Prepare the source**: download/unpack the collection to a temporary location (e.g., `beta/` or the system temp dir); never put it directly into `stdskills/`. Common layouts:
   - Single skill folder: contains `SKILL.md` directly
   - Skill collection repo (e.g., `anthropics/skills`): skills under `skills/<skill-name>/SKILL.md`
   - Packaged repo (e.g., `xxx-main/` after download): same layout, `skills/<skill-name>/SKILL.md`
2. **Install via tool**: call `skill_stdskill_helper_install_skill` with `source` set to the **absolute path** of the source folder. The tool automatically:
   - Finds every `SKILL.md` recursively (single / collection / packaged repo all work)
   - Parses the frontmatter name and validates its format
   - Copies only the skill folder itself and discards repository scaffolding (`.git`, `.github`, `.claude-plugin`, README, LICENSE, etc.)
   - Skips skills whose name already exists
3. **Check the result**: the tool returns three lists: `installed`, `skipped`, `failed`; confirm there are no unexpected failures
4. **Verify**: call `skill_stdskill_helper_list_skills` to confirm the skill now appears
5. **Tell the user**: the new skill takes effect after Dolphin restarts, as tool `stdskill_<skill-name>`

## Option 2: Create a new skill

Applies when the user wants a brand-new capability not covered by existing skills.

### Steps

1. **Define metadata**: confirm `name` and `description` with the user:
   - `name`: hyphen-separated words (e.g., `file-organizer`), short and descriptive
   - `description`: phrased as "Use when the user needs ..."; state the trigger scenario; do not describe implementation details
2. **Write the body**: follow the quality guidelines below
3. **Create via tool**: call `skill_stdskill_helper_create_skill` with:
   - `name`: the skill name
   - `description`: a one-sentence trigger description
   - `content`: the SKILL.md body (without frontmatter; the tool generates it). If you pass a complete SKILL.md text (starting with `---`), it is used as-is
   - `overwrite`: set to true only if the name already exists and the user explicitly wants to overwrite
4. **Tell the user**: the new skill takes effect after Dolphin restarts, as tool `stdskill_<skill-name>`

## How to Write a Good SKILL.md Body (prompt quality guidelines)

The body is the prompt the model reads; its quality determines the skill's effectiveness. Distilled from the prompt cases under `beta/` on this machine:

1. **Specific beats vague** — every instruction must be actionable:
   - Correct: "List all files in the target directory with file_manager, sorted by modification time descending"
   - Incorrect: "Look at the files"
2. **Give executable steps** — describe the process with numbered steps, not just conclusions:
   - Correct: "1. Read the target file -> 2. Inspect key fields -> 3. Summarize into a table"
   - Incorrect: "Analyze the code and give feedback"
3. **Specify the output format** — state the structure and presentation of results (sections, tables, `[skills]` label, etc.)
4. **Cover edge cases** — describe how to handle unusual scenarios: no results, permission errors, missing directories, oversized input, etc.
5. **Make quality measurable** — define what "good" means (e.g., "every finding includes a file:line reference")
6. **Address the model directly** — use "You need to ...", not "This skill will ..."
7. **Trigger with verbs in the description** — start the frontmatter `description` with verbs (start / run / build / test / generate ...), since it is scanned to decide whether to call the skill
8. **Self-test when done** — could a model that has never seen the current conversation complete the task from the body alone?

## Optional Subdirectories

| Directory | Purpose |
|---|---|
| `scripts/` | Executable scripts, run by the model via `powershell_executor`'s `run_script` |
| `assets/` | Static resources required by the skill |
| `references/` or `reference/` | Supplementary docs referenced in the body |

When installing an external skill, these subdirectories are copied along with the skill folder (only if the skill needs them).

## Checklist (run after install or create)

- [ ] Tool returned `success: true` with no `failed` entries
- [ ] The `installed` list contains the expected skill name (or `skipped` notes it already exists)
- [ ] `skill_stdskill_helper_list_skills` confirms the skill is present
- [ ] Told the user: the new skill takes effect after Dolphin restarts, as tool `stdskill_<skill-name>`

## Examples

Install a GitHub collection:

```
1. Download and unpack the repo into beta/ (e.g., beta/skills-repo-main/)
2. Call skill_stdskill_helper_install_skill(source="D:\codes\QuickAI\beta\skills-repo-main")
3. Returns: installed=["design-taste-frontend", "minimalist-ui"], skipped=[], failed=[]
4. Verify with skill_stdskill_helper_list_skills
5. Tell the user: restart to enable stdskill_design-taste-frontend etc.
```

Create a "batch file rename" skill:

```
1. Confirm with the user: name="file-organizer", description="Use when the user needs to batch-rename or organize files in a directory by rules"
2. Write the body:
   1. List all files in the target directory with file_manager
   2. Confirm the rename rules with the user (prefix, numbering, extension grouping, etc.)
   3. Rename file by file, then summarize the result with the [skills] label
3. Call skill_stdskill_helper_create_skill(name="file-organizer",
     description="Use when the user needs to batch-rename or organize files in a directory by rules",
     content="1. List all files in the target directory with file_manager\n2. Confirm the rename rules with the user\n3. Rename file by file, then summarize the result with the [skills] label")
4. Tell the user: restart to enable stdskill_file-organizer
```

## References (local only; `beta/` is not tracked)

When writing prompts you may consult the cases and tutorials under `beta/` on this machine:

- `beta/system-prompt-design.md` — full guide to system prompt design patterns (core structure, 4 agent modes, style rules, common pitfalls, length & testing advice)
- `beta/system-prompts/system-prompt-writing-subagent-prompts.md` — key points for writing delegation-style prompts
- `beta/system-prompts/skill-run-skill-template.md` — concrete skill template example (includes description verb advice)
- `beta/system-prompts/` — hundreds of real cases (`system-prompt-*`, `agent-prompt-*`, `skill-*`) for reference

Note: `beta/` is gitignored and may not exist on other machines; check the path before referencing. The guidelines in this skill are self-contained and do not depend on those files.
