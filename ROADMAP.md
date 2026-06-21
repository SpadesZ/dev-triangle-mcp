# Roadmap

## v0.1 Current

- Stable Codex + Jules + Antigravity workflow.
- Main MCP server for Codex.
- Report-only MCP server for Antigravity.
- Local productization scripts.
- Windows and Ubuntu CI smoke tests.

## v0.2 Provider Profiles

- Add a provider profile loader.
- Keep current `jules_*` and `antigravity_*` tools as compatibility wrappers.
- Add schema validation for provider profiles.
- Add tests for default profile loading.

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

- No generic shell executor exposed over MCP.
- No secrets written into repo or user config.
- No worker agent gets the full control-plane server by default.
