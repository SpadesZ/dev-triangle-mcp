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

Dev Triangle MCP does not expose a *generic* shell executor as an MCP tool.

Antigravity execution goes through an explicit handoff route. The stable
unattended path is:

```text
agy --print
```

Antigravity receives a bounded task and reports completion through
`dev-triangle-report`.

### Verification suite runner (named exception)

Local verification runs real commands on your machine. This is a deliberate,
scoped exception approved on 2026-08-19, not a general shell tool. Three
conditions bind it (see `docs/SAI.md` S7.1):

1. Commands come only from the target repo's own `.dev-triangle/verify.json`.
2. The MCP tool takes `repoPath`, `suiteName`, and `confirmSuite` — there is no
   `command` parameter, so callers cannot supply command strings.
3. Every command, exit code, and captured output is written to the ledger so a
   claimed pass can be re-run and checked later.

**Attack surface.** `verify.json` lives inside the repo you point at. Cloning a
hostile repo and verifying it would otherwise hand that repo code execution on
your machine.

**Defence.** The runner hashes `verify.json` **together with the current
`git rev-parse HEAD`** and compares it against the hashes you have already
confirmed. A first sighting, an edited `verify.json`, or a moved HEAD all return
`NEEDS_CONFIRMATION` with the full command text, and nothing runs until the
caller passes `confirmSuite: true`.

Binding the hash to the commit is what closes the time-of-check/time-of-use gap:
without it, a patch applied after confirmation could rewrite the test scripts
that `verify.json` points at while leaving `verify.json` itself untouched.

**This confirmation is not covered by the "no confirmation prompts" decision for
configuration changes.** That decision was about you configuring your own tools.
This gate is about a third party's files running commands on your machine.
Removing it would revoke the approval that allows the runner to exist at all.

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
