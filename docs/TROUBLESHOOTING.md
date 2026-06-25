# Troubleshooting

Start with:

```powershell
.\scripts\doctor.ps1
```

Then run:

```powershell
.\scripts\smoke.ps1
```

If both pass, the MCP protocol and local config are usually healthy. If a real
worker still fails, inspect the worker-specific section below.

## Common Symptoms

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Codex cannot see `dev_triangle` | Codex config missing or points at the wrong path | Re-run `scripts\install-local.ps1`, then restart Codex |
| Antigravity sees `dev_triangle` instead of `dev-triangle-report` | Worker config has the full control-plane server | Re-run installer; worker agents should see report-only MCP |
| `JULES_API_KEY` missing | Key was not exported in the shell or environment | Set `$env:JULES_API_KEY = "your key"` before starting the client |
| Jules returns unauthorized | Wrong or expired key | Refresh the key and keep it out of Git |
| `prepare_jules_repo` is blocked | Secret-looking files, dirty repo, or missing confirmation | Read `safety.blockingFindings`, commit/ignore/remove risky files, then rerun |
| `agy` not found | Antigravity CLI is missing or not on PATH | Install Antigravity CLI or set `ANTIGRAVITY_COMMAND` |
| Handoff stuck at `AWAITING_RESULT` | Worker launched but did not submit a report | Check result path, result marker, and Antigravity output |
| Handoff returns `DEGRADED_NO_RESULT` | `agy --print` exited 0 with empty stdout and no result file | Check report MCP config, result path permissions, and avoid unverified model labels |
| Result file exists but is not ready | Missing `DEV_TRIANGLE_RESULT_READY` marker | Have the worker submit through `complete_dev_triangle_handoff` |
| Smoke test passes but real demo fails | Protocol is healthy, real CLI/auth/model path is not | Run `doctor.ps1`, then test `agy --version` and the demo again |
| CI passes but local worker fails | CI uses fake worker paths | Use `demo-user-flow.ps1` for real local validation |

## Codex Config Problems

Expected Codex config shape:

```toml
[mcp_servers.dev_triangle]
command = "python"
args = ["C:\\path\\to\\dev-triangle-mcp\\server.py"]
```

Expected behavior:

```text
Codex sees the full dev_triangle server.
Codex can call Jules, Antigravity handoff, health, and ledger tools.
```

Fix:

```powershell
.\scripts\install-local.ps1
```

Then restart Codex so it reloads MCP config.

## Antigravity Config Problems

Expected worker config shape:

```json
{
  "mcpServers": {
    "dev-triangle-report": {
      "command": "python",
      "args": ["C:\\path\\to\\dev-triangle-mcp\\antigravity_report_server.py"]
    }
  }
}
```

Expected behavior:

```text
Antigravity sees dev-triangle-report only.
Antigravity can call complete_dev_triangle_handoff.
Antigravity cannot call Jules tools.
```

Fix:

```powershell
.\scripts\install-local.ps1
```

Then restart Antigravity.

## Jules Problems

Check whether the key exists in the current shell:

```powershell
if ($env:JULES_API_KEY) { "present" } else { "missing" }
```

Set it for the current shell:

```powershell
$env:JULES_API_KEY = "your key"
```

Do not put the key in:

- `README.md`
- `config/*.json`
- `config/*.toml`
- `jobs.json`
- handoff files
- result files
- screenshots

If the key is present but Jules still fails:

1. Confirm the key is valid.
2. Confirm the target repo is connected to Jules.
3. If the project is local-only, run `prepare_jules_repo` before creating the Jules session.
4. Use `jules_list_sources` before `jules_create_session`.
5. Use `jules_list_activities` to inspect plan or execution state.

## `prepare_jules_repo` Problems

`prepare_jules_repo` defaults to dry-run:

```text
publish=false
```

To actually create and push a repo:

```text
publish=true
confirmPublish=true
```

Common blockers:

- A likely secret is present and would be tracked.
- The project is already a git repo with uncommitted changes.
- `gh` is not installed or not authenticated.
- The target GitHub repo already exists but is not connected as a remote.
- Public visibility was requested without `confirmPublic=true`.

The safe default is private GitHub repo creation. If Jules still cannot see the
repo after publishing, the GitHub repo may need to be allowed in Jules/GitHub app
permissions before `jules_create_session` can use it.

## Antigravity CLI Problems

Check:

```powershell
agy --version
```

If that fails, find the CLI:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\agy\bin" -ErrorAction SilentlyContinue
```

You can point Dev Triangle MCP at a specific executable:

```powershell
$env:ANTIGRAVITY_COMMAND = "$env:LOCALAPPDATA\agy\bin\agy.exe"
```

Then run:

```powershell
.\scripts\doctor.ps1
```

### `agy --print` exits 0 but stdout is empty

This can happen even when Antigravity authenticated and hit the model stream.
The CLI may emit planner or tool-call events without a final printable response.
Dev Triangle therefore treats stdout as diagnostic only; a handoff is complete
only when `complete_dev_triangle_handoff` is called or the result file contains
`DEV_TRIANGLE_RESULT_READY`.

Common causes:

- The worker did not submit through `dev-triangle-report`.
- The result file was not written under the allowed result directory.
- `ANTIGRAVITY_AGY_MODEL` names a model label that is not available locally.
- The agent spent the run planning or calling tools and never produced a final
  report.

Fixes:

- Leave `ANTIGRAVITY_AGY_MODEL` unset unless you have verified the exact local
  label.
- Dev Triangle ignores the legacy unsafe `Gemini 3.5 Flash (Medium)` value even
  when a parent process still has it in the environment.
- Run `mcp_health_check` with `includeAntigravityPrintSmoke=true` when you need
  to diagnose headless output.
- Prefer the report-only MCP path: `complete_dev_triangle_handoff`.
- If stdout is empty and no result file appears, Dev Triangle should report
  `DEGRADED_NO_RESULT` instead of waiting for the full result timeout.

## Handoff Stuck At `AWAITING_RESULT`

This means Dev Triangle MCP created or launched the handoff, but Codex has not
seen a completed result yet.

Check the handoff in:

```text
%USERPROFILE%\.dev-triangle\antigravity-handoffs
```

Check results in:

```text
%USERPROFILE%\.dev-triangle\antigravity-results
```

A valid result should include:

```text
DEV_TRIANGLE_RESULT_READY
```

If the marker is missing, the result is not considered ready.

Common fixes:

- Tell Antigravity to call `complete_dev_triangle_handoff`.
- Re-run the handoff with `waitForResult=true`.
- Use the stable `agy_print` execution style.
- Increase `resultTimeoutSec` if the local task takes longer.

## Real Demo Fails But Smoke Test Passes

This is possible and useful information.

Smoke tests prove:

- The MCP server starts.
- JSON-RPC works.
- Tools are registered.
- The fake closed-loop mailbox contract works.

The real demo proves:

- `agy` is installed.
- Antigravity can run unattended.
- The local worker can submit a real result.

If smoke passes but demo fails, the MCP protocol is probably fine. Focus on
Antigravity CLI, auth, model availability, local permissions, or timeout.

## Cleaning Local State

Runtime state lives here:

```text
%USERPROFILE%\.dev-triangle
```

You can archive or remove old handoffs and results if they are no longer useful.
Do not delete state while a worker is currently running.

Ignored repo-local test folders:

```text
.dev-triangle-test/
.dev-triangle-report-test/
demo-output/
logs/
```

## What To Include In A Bug Report

Include:

- Operating system.
- Python version.
- Output of `scripts\doctor.ps1`.
- Output of `scripts\smoke.ps1`.
- Whether `agy --version` works.
- Whether `JULES_API_KEY` is present, without sharing the key.
- The handoff id if the issue involves Antigravity.
- The final status from `jobs.json`.

Do not include:

- API keys.
- Private source code unless you intentionally want to share it.
- Full result logs that contain secrets.
