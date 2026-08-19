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
  An all-empty provider profile template. Copy it to
  providers.<your-name>.json, fill it in, and select it with
  DEV_TRIANGLE_PROFILE. The file name is the profile name.
```

## Provider Profiles

The seven role slots (`orchestrator`, `contextBroker`, `architect`,
`cloudWorker`, `verifier`, `diagnostician`, `reporter`) are fixed by this
project. What each one is called and which model it uses is yours:

```text
slot key      fixed by this project   renaming it silently breaks the role
displayName   yours                   any text, any language, safe to change
model/baseUrl/apiKeyEnv   yours       this project never fills these in
```

Two rules worth knowing before you edit:

- **Empty means "not configured", not "use a default".** An `api` role with no
  `model` refuses to run and tells you which line to fill. This project does not
  pick a model for you.
- **`apiKeyEnv` is a variable NAME, not a key.** Put the key in your shell
  environment and write the variable's name here. Values that look like
  credentials are rejected at load time.

Check what is currently bound:

```powershell
$env:DEV_TRIANGLE_PROFILE = "example"
python -c "from providers.profiles import load_profile; print(load_profile('example').describe())"
```

or call the `mcp_health_check` tool and read its `profile` block.

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
