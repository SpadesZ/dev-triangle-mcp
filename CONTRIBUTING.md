# Contributing

Thanks for improving Dev Triangle MCP.

This project is small on purpose. The most important contribution rule is:

```text
Keep the workflow easy to understand and hard to misuse.
```

## Local Setup

Clone:

```powershell
git clone https://github.com/SpadesZ/dev-triangle-mcp.git
cd dev-triangle-mcp
```

Install local config if you want to test with real clients:

```powershell
.\scripts\install-local.ps1
```

Run diagnostics:

```powershell
.\scripts\doctor.ps1
```

## Tests

Compile:

```powershell
python -m py_compile server.py antigravity_report_server.py tests\protocol_smoke.py tests\report_server_smoke.py
```

Run deterministic protocol tests:

```powershell
python tests\protocol_smoke.py
python tests\report_server_smoke.py
```

Run the wrapper:

```powershell
.\scripts\smoke.ps1
```

Run the real local demo if you have Antigravity `agy` installed:

```powershell
.\scripts\demo-user-flow.ps1
```

## What CI Covers

CI runs on Windows and Ubuntu.

It checks:

- Python syntax.
- Main MCP protocol behavior.
- Report-only MCP protocol behavior.
- Fake closed-loop result capture.

CI does not call real Jules or real Antigravity. External credentials should not
be required for public CI.

## Coding Principles

Prefer:

- Small, explicit tools.
- Narrow JSON schemas.
- Plain data structures.
- Human-readable errors.
- Local state outside the source tree.
- Worker permissions that are as small as possible.

Avoid:

- Generic shell execution tools.
- Writing secrets to config files.
- Giving worker agents the full control plane.
- Hidden network calls in tests.
- Mock results presented as real worker completion.

## Documentation Principles

Write docs for a tired human.

Good docs should answer:

- What is this?
- When should I use it?
- What command do I run first?
- What does success look like?
- What can go wrong?
- Where is the result stored?
- What should I never commit?

Use simple examples. Prefer concrete paths with placeholders over abstract
phrasing.

## Pull Request Checklist

Before opening a PR:

- Run `python -m py_compile ...`.
- Run `python tests\protocol_smoke.py`.
- Run `python tests\report_server_smoke.py`.
- Update docs if behavior changed.
- Confirm no secrets or local runtime state are committed.

Useful secret scan:

```powershell
rg -n "JULES_API_KEY\\s*=|AQ\\.|\\.dev-triangle|AppData\\\\Local\\\\Temp" .
```

Some matches may be documentation examples. Real keys, local screenshots, and
private result files should never be committed.

## Provider Work

Provider abstraction is planned, but the stable default must remain:

```text
Codex -> Jules -> Antigravity
```

If you add provider work, keep existing `jules_*` and `antigravity_*` tools
compatible unless the change is intentionally breaking and documented.
