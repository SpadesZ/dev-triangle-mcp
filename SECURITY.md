# Security

Dev Triangle MCP coordinates coding agents. Treat it as workflow
infrastructure, not as a place to store secrets.

## Secrets

Do not commit API keys or tokens.

Jules credentials should be provided through the environment:

```powershell
$env:JULES_API_KEY = "your key"
```

The local installer does not write `JULES_API_KEY` to Codex, Antigravity,
Gemini, or repo config files.

Do not paste secrets into:

- README files.
- MCP config examples.
- handoff markdown.
- result markdown.
- `jobs.json`.
- screenshots.
- issue comments.

## Local Execution

Dev Triangle MCP does not expose a generic shell executor as an MCP tool.

Antigravity execution goes through an explicit handoff route. The stable
unattended path is:

```text
agy --print
```

Antigravity receives a bounded task and reports completion through
`dev-triangle-report`.

## Permission Boundaries

Recommended setup:

```text
Codex -> full dev_triangle MCP
Workers -> dev-triangle-report MCP only
```

This prevents normal worker agents from creating unrelated Jules sessions,
mutating the whole ledger, or launching other tools.

## What Not To Publish

Do not publish:

- `.dev-triangle`
- `.dev-triangle-test`
- `.dev-triangle-report-test`
- `demo-output`
- `logs`
- handoff/result history
- local API keys
- local screenshots that show private tokens or paths

These are ignored by default where possible, but you should still review
commits before pushing.

## Reporting Security Issues

Please avoid posting secrets or private logs in public issues.

For now, open a GitHub issue with a minimal reproduction that omits keys and
private project data. If the issue involves a secret leak, rotate the affected
secret before sharing details.
