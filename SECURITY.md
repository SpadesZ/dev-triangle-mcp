# Security

## Secrets

Do not commit API keys or tokens.

Jules credentials should be provided through the environment:

```powershell
$env:JULES_API_KEY = "..."
```

The local installer does not write `JULES_API_KEY` to Codex, Antigravity, Gemini, or repo config files.

## Local Execution

Dev Triangle MCP does not expose a generic shell executor as an MCP tool.

Antigravity execution goes through its explicit CLI route:

```text
agy --print
```

Antigravity receives a handoff and reports completion through `dev-triangle-report`.

## What Not To Publish

Do not publish:

- `.dev-triangle`
- `.dev-triangle-test`
- `.dev-triangle-report-test`
- `demo-output`
- logs
- handoff/result history
- local API keys

These are ignored by default.
