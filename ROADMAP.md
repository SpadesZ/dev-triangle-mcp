# Roadmap

## Current Accepted Baseline — 2026-08-20

- Role-based control plane with seven fixed slots and user-selected bindings.
- API and CLI dispatch by `binding.kind`; no vendor hard-coding in routing.
- Explicit whole-profile activation, persistence, audit history, and undo.
- Real three-account route:
  `Codex -> Gemini Context Broker -> Claude Architect -> deterministic verifier`.
- Reviewed patch application with clean-tree protection and rollback evidence.
- `SUCCESS` gated by target-repo machine evidence and exit code 0.
- One bounded self-heal attempt after a verification failure.
- Outbound repository allowlist and fail-closed secret redaction.
- CLI usage reports calls separately and marks token counts unavailable when the
  CLI does not provide them.
- `jules_*` and `antigravity_*` retained as compatibility routes.
- Main MCP protocol: 30 tools. Report-only MCP: 2 tools.
- Accepted revision: 162 tests plus protocol, report, smoke, doctor, real CLI,
  and rollback acceptance.

## Completed Work Packages

| Package | Outcome |
| --- | --- |
| W00-W13 | Deterministic evidence gate, profile schema, Broker-Architect route, redaction, patch gate, self-heal, and configuration audit |
| W14 | CLI agents decoupled from named roles; dispatch routes by `kind` |
| W15 | Whole-profile activation and undo |
| W16 | Installer/doctor orchestrator detection accepts configured Codex or Claude clients |
| W17 | Installer supports `codex`, `claude`, or `both` orchestrator setup |
| W18 | Usage calls and tokens separated; unavailable CLI totals remain explicit |

See [docs/SAI.md](docs/SAI.md) for the governing invariants and
[docs/HANDOFF.md](docs/HANDOFF.md) for acceptance evidence.

## Remaining Deployment Work

- Complete and re-check optional Claude Code user-scope MCP registration across
  an application restart. Project-scope `.mcp.json` is already supported.
- Re-run CLI flag, stdin, JSON, timeout, and write-policy probes after provider
  CLI upgrades.
- Add a new provider binding only when there is a real-path acceptance case;
  mocks alone are not enough to advertise it as validated.

## Non-Goals

- No generic shell executor over MCP. The verification runner executes only
  allowlisted commands declared by the target repo.
- No secrets in repository or provider profile files.
- No worker or diagnostician receives the full control-plane server by default.
- No automatic provider failover or silent model downgrade.
- No agent assertion may substitute for machine verification.
