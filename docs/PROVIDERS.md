# Provider Model

Dev Triangle MCP currently ships with one stable runtime stack:

```text
Codex -> Dev Triangle MCP -> Jules -> Antigravity
```

This document describes the provider abstraction planned for future versions. It is documentation only for now; the current runtime defaults remain unchanged.

## Roles

```text
orchestrator
  The agent the user is talking to. It owns task planning, routing, review, and final answers.

cloud_code_worker
  A remote worker for larger code changes, repetitive edits, dependency upgrades, or patch/PR generation.

local_verifier
  A local agent or CLI that can run project-specific validation, inspect local files, use local tools, and report back.

reporter
  A narrow return channel that lets workers submit results without seeing the full control plane.
```

## Current Stable Profile

```text
profile: codex-jules-antigravity

orchestrator: Codex
cloud_code_worker: Jules
local_verifier: Antigravity through agy
reporter: dev-triangle-report MCP
```

## Example Future Profiles

Claude as the orchestrator:

```text
profile: claude-jules-antigravity

orchestrator: Claude
cloud_code_worker: Jules
local_verifier: Antigravity through agy
reporter: dev-triangle-report MCP
```

Gemini CLI as the code worker:

```text
profile: codex-gemini-antigravity

orchestrator: Codex
cloud_code_worker: Gemini CLI
local_verifier: Antigravity through agy
reporter: dev-triangle-report MCP
```

Claude plus Gemini:

```text
profile: claude-gemini-antigravity

orchestrator: Claude
cloud_code_worker: Gemini CLI
local_verifier: Antigravity through agy
reporter: dev-triangle-report MCP
```

## Design Rule

Only the orchestrator should see the full control-plane MCP server.

Workers should receive narrow task input and a narrow reporting surface. This prevents worker agents from accidentally calling unrelated tools, creating circular delegation, or touching secrets they do not need.

```text
orchestrator -> full dev_triangle MCP
worker       -> task prompt + report-only MCP
verifier     -> handoff + report-only MCP
```

## Implementation Direction

The next implementation step is to introduce a provider registry:

```text
providers/
  jules.py
  antigravity.py
  gemini_cli.py
  claude_code.py
```

Each provider should implement the same minimal lifecycle:

```text
detect
create_task
run_or_resume
get_result
submit_result
```

The current `jules_*` and `antigravity_*` tools can then become stable compatibility wrappers around the provider registry.
