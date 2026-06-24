# New Project Workflow

This document explains how to use Dev Triangle MCP on a new project from the
user's point of view.

## Prerequisites

Required:

- Windows PowerShell.
- Python 3.10 or newer, or the bundled Codex Python runtime.
- Codex with MCP support.
- This repository cloned locally.

Optional but useful:

- Jules API access through `JULES_API_KEY`.
- Antigravity CLI, especially `agy`.
- GitHub CLI if you want PR and CI checks.

## One-Time Install

From the repo:

```powershell
.\scripts\install-local.ps1
```

This writes or updates:

```text
%USERPROFILE%\.codex\config.toml
%USERPROFILE%\.gemini\config\mcp_config.json
%APPDATA%\Antigravity IDE\User\mcp.json
```

The important split:

```text
Codex config:
  dev_triangle -> server.py

Antigravity/Gemini config:
  dev-triangle-report -> antigravity_report_server.py
```

The installer backs up existing config files before modifying them.

## Check The Install

Run:

```powershell
.\scripts\doctor.ps1
```

A healthy output should say `Dev Triangle MCP doctor: pass`.

If a check fails, read the failed line first. The most common failures are:

- Python not found.
- `agy` not found.
- Codex config does not point at this repo.
- Antigravity config has the wrong server.

See [Troubleshooting](TROUBLESHOOTING.md) for fixes.

## Smoke Test

Run:

```powershell
.\scripts\smoke.ps1
```

This proves the MCP protocol works. It does not require real Jules or
Antigravity auth. It uses deterministic fake/local paths where needed.

Expected result:

```text
status: pass
```

## Real Local Demo

Run:

```powershell
.\scripts\demo-user-flow.ps1
```

This creates a tiny demo project, creates an Antigravity handoff, runs `agy`,
waits for the report-only MCP result, and writes a JSON report.

This is the closest automated check to the real user experience.

Expected shape:

```text
status: COMPLETED
resultReady: true
agyExitCode: 0
```

If `JULES_API_KEY` is not set, the demo may skip the Jules route. That is
expected. Jules is optional until you want cloud coding work.

## Use It On Your Own Project

Open Codex in or near your project and say:

```text
Use Dev Triangle MCP for this project:
C:\path\to\my-project

Goal:
describe the thing you want built, fixed, tested, reviewed, or validated.
```

Good goal examples:

```text
Add smoke tests for the CLI parser and run them locally.
```

```text
Have Jules upgrade the old API usage across the repo, then have Codex review the
patch and run local tests.
```

```text
Create an Antigravity handoff to verify Docker startup and submit a final
report back to Codex.
```

## The Route Codex Should Choose

### Route 1: Codex Only

Use when the task is small.

Flow:

```text
User -> Codex -> local edit/test -> final answer
```

No MCP delegation is necessary, though Codex may still use MCP health checks.

### Route 2: Jules

Use when the task is large or repetitive.

Flow:

```text
User -> Codex -> dev_triangle MCP -> Jules -> outputs/patch/PR -> Codex review
```

Before creating a Jules session, Codex should check:

- Is `JULES_API_KEY` available?
- Is the project already in a GitHub repo Jules can see?
- Is the task clear enough to delegate?
- Should plan approval be required?

If the project is only a local folder, Codex should first call
`prepare_jules_repo`.

Safe repo preparation flow:

```text
prepare_jules_repo publish=false
  -> inspect git state
  -> scan for secrets and risky files
  -> show planned private GitHub repo/source

prepare_jules_repo publish=true confirmPublish=true
  -> add safe .gitignore defaults
  -> git init if needed
  -> create initial commit if needed
  -> create private GitHub repo if needed
  -> push branch
  -> return source usable by jules_create_session
```

The tool defaults to dry-run. Public repos require an extra `confirmPublic=true`
guard.

The default should be `requirePlanApproval=true` so a human or orchestrator can
review the plan before code changes proceed.

### Route 3: Antigravity

Use when the task needs local verification.

Flow:

```text
User -> Codex -> create handoff -> agy --print -> report MCP -> Codex result
```

Codex should include:

- The project path.
- The objective.
- Relevant files.
- Suggested commands.
- Acceptance criteria.

Antigravity should finish by calling:

```text
complete_dev_triangle_handoff
```

or by writing a result file that contains:

```text
DEV_TRIANGLE_RESULT_READY
```

### Route 4: Full Triangle

Use when you want broad implementation plus local validation.

Flow:

```text
User
  -> Codex
  -> Jules for code work
  -> Codex review
  -> Antigravity local verification
  -> Codex final recommendation
```

This is the route for higher-confidence automation.

## What Codex Should Report Back

A good final answer should include:

- What route was used.
- What changed or what was verified.
- Where the result is recorded.
- Which commands/tests ran.
- Whether the loop completed.
- Any risks or next steps.

Example:

```text
Dev Triangle route used: Antigravity local verification.
Handoff status: COMPLETED.
Result marker: DEV_TRIANGLE_RESULT_READY.
Commands run: python -m py_compile, python smoke_test.py.
Recommendation: ready to merge.
```

## What Not To Do

Do not paste API keys into prompts or docs.

Do not attach the full `dev_triangle` MCP server to worker agents unless you
intentionally want them to orchestrate other tools.

Do not treat a fake worker smoke test as proof that real Jules or real
Antigravity completed work.

Do not commit:

```text
.dev-triangle/
.dev-triangle-test/
.dev-triangle-report-test/
demo-output/
logs/
```

## Stable Ending Conditions

For a task to be considered done, at least one of these should be true:

- Codex completed the local change and tests passed.
- Jules produced outputs and Codex reviewed them.
- Antigravity returned `COMPLETED` with `DEV_TRIANGLE_RESULT_READY`.
- CI passed after pushing the change.

For important work, prefer:

```text
Jules or Codex implementation -> Antigravity local verification -> CI -> Codex final answer
```
