# Config Examples

This folder contains copyable examples. They are not machine-specific live
config.

Most users should run:

```powershell
.\scripts\install-local.ps1
```

The installer writes the correct absolute paths for your machine and backs up
existing config files before changing them.

## Files

```text
codex.config.toml
  Example full control-plane MCP config for Codex.

antigravity.mcp_config.json
  Example report-only MCP config for Antigravity/Gemini.

providers.example.json
  Future provider profile examples. This does not change runtime behavior yet.
```

## The Important Split

Codex should see:

```text
dev_triangle -> server.py
```

Antigravity and Gemini-side worker config should see:

```text
dev-triangle-report -> antigravity_report_server.py
```

Reason:

```text
Codex orchestrates the whole workflow.
Workers only need to submit final results.
```

Do not attach the full `dev_triangle` server to worker/verifier agents unless
you intentionally want them to have orchestration permissions.

## Secrets

Do not put real API keys in these example files.

For Jules, set:

```powershell
$env:JULES_API_KEY = "your key"
```

The installer allows Codex to inherit the environment variable, but it does not
write the key to disk.

## When To Edit Manually

Manual edits are useful when:

- Your repo is not in the default location.
- You want a custom Python path.
- You want a custom `agy` path.
- You are testing a future provider profile.

After manual edits, run:

```powershell
.\scripts\doctor.ps1
```
