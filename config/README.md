# Config Examples

This folder contains copyable examples, not machine-specific live config.

Use:

```powershell
.\scripts\install-local.ps1
```

to write local Codex and Antigravity/Gemini config files with the correct paths
for your machine.

## Files

```text
codex.config.toml
  Example full control-plane MCP config for Codex.

antigravity.mcp_config.json
  Example report-only MCP config for Antigravity/Gemini.

providers.example.json
  Future provider profile examples. This does not change runtime behavior yet.
```

## Important Split

Codex should see:

```text
dev_triangle -> server.py
```

Antigravity should see:

```text
dev-triangle-report -> antigravity_report_server.py
```

Do not attach the full `dev_triangle` server to worker/verifier agents unless
you intentionally want them to have orchestration permissions.
