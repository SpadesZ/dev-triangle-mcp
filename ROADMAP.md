# Roadmap

## v0.1 Current

- Stable Codex + Jules + Antigravity workflow.
- Main MCP server for Codex.
- Report-only MCP server for Antigravity.
- Local productization scripts.
- Windows and Ubuntu CI smoke tests.

## v0.2 Provider Profiles — done 2026-08-19

- ✅ Provider profile loader (`providers/profiles.py`).
- ✅ `jules_*` and `antigravity_*` kept as compatibility wrappers.
- ✅ Schema validation, including fixed slot keys and environment-variable-name
  checking for `apiKeyEnv`.
- ✅ Tests for profile loading. Note the deliberate reversal: there is no default
  profile to test, because a missing profile raises and lists what exists rather
  than falling back.

## v0.2.1 Deterministic Verification — done 2026-08-19

Reordered ahead of the worker adapters. The original sequence put model swapping
first and quality gates last; the only thing actually broken was that nothing
produced an exit code, and swapping models first would only have made an
unmeasured pipeline run faster. See `docs/SAI.md` I1.

- ✅ Restricted verification suite runner reading `.dev-triangle/verify.json`.
- ✅ Quality gate: `SUCCESS` requires machine evidence and exit code 0.
- ✅ Ledger schema v2, additive, old jobs not migrated.
- ✅ Outbound payload masking, fail-closed.
- ✅ Self-heal, one retry, hard-capped in code.
- ✅ Natural-language configuration bridge.

## v0.3 Gemini CLI Worker Adapter

- Add a Gemini CLI worker adapter.
- Support task creation through a narrow worker prompt.
- Require result submission through the report-only MCP or explicit mailbox contract.

## v0.4 Claude Orchestrator Documentation

- Document Claude Desktop / Claude API MCP setup.
- Provide example config for Claude as the orchestrator.
- Keep runtime behavior unchanged unless explicitly selected through a provider profile.

## v0.5 Provider Test Matrix

- Add CI tests for provider profile parsing.
- Add fake providers for deterministic worker lifecycle tests.
- Add integration docs for Codex, Claude, Gemini CLI, Jules, and Antigravity.

## Non-Goals

- No generic shell executor exposed over MCP. The verification suite runner is
  a named exception, not a relaxation: it runs only allowlisted commands that
  the target repo declares in `.dev-triangle/verify.json`, and callers cannot
  supply command strings. See `docs/SAI.md` S7.1.
- No secrets written into repo or user config.
- No worker agent gets the full control-plane server by default.
