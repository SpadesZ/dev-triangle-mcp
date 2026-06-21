# Architecture

Dev Triangle MCP keeps orchestration, worker execution, and result reporting as
separate responsibilities.

The design is intentionally conservative:

```text
One orchestrator sees the full control plane.
Workers receive narrow tasks.
Workers report back through a narrow result surface.
Runtime state stays outside the source tree.
```

## Components

```mermaid
flowchart LR
  User["User"] --> Codex["Codex orchestrator"]
  Codex --> Main["dev_triangle MCP server.py"]
  Main --> Jules["Jules cloud coding API"]
  Main --> Handoff["Handoff markdown"]
  Handoff --> Agy["Antigravity agy --print"]
  Agy --> Report["dev-triangle-report MCP"]
  Report --> State["jobs.json + result markdown"]
  Main --> State
  State --> Codex
```

## Responsibilities

| Component | Responsibility | Should do | Should not do |
| --- | --- | --- | --- |
| Codex | Orchestration | Understand the user, route work, review results | Blindly trust worker output |
| `server.py` | Main MCP control plane | Jules calls, handoffs, ledger, health checks | Expose generic shell execution |
| Jules | Cloud coding | Larger edits, repetitive work, PR/patch output | Receive local secrets |
| Antigravity | Local verification | Local checks, environment validation, report writing | Control the whole workflow |
| `antigravity_report_server.py` | Report-only MCP | Accept final worker reports | Create Jules sessions or launch tools |
| `jobs.json` | Local ledger | Track statuses and result paths | Store secrets |

## Why Two MCP Servers?

The full server and report server have different trust levels.

### Full Server

Name:

```text
dev_triangle
```

File:

```text
server.py
```

This server is for the orchestrator. It can call Jules, create and run
Antigravity handoffs, inspect the ledger, and update jobs.

### Report Server

Name:

```text
dev-triangle-report
```

File:

```text
antigravity_report_server.py
```

This server is for workers. It exposes only:

- `dev_triangle_report_health`
- `complete_dev_triangle_handoff`

This keeps worker agents focused. They can submit a result, but they cannot
start unrelated cloud sessions or mutate the whole workflow.

## Antigravity Closed Loop

```mermaid
sequenceDiagram
  participant C as Codex
  participant M as dev_triangle
  participant A as agy
  participant R as dev-triangle-report
  participant S as State

  C->>M: create_antigravity_handoff
  M->>S: write handoff + ledger entry
  C->>M: run_antigravity_handoff(waitForResult=true)
  M->>A: agy --print "handoff prompt"
  A->>R: complete_dev_triangle_handoff
  R->>S: write result markdown
  R->>S: update handoff status to COMPLETED
  M->>S: poll result path
  M->>C: return status + report content
```

The completion marker is:

```text
DEV_TRIANGLE_RESULT_READY
```

If that marker is missing, Codex should not treat the handoff as fully ready.

## Jules Loop

```mermaid
sequenceDiagram
  participant C as Codex
  participant M as dev_triangle
  participant J as Jules
  participant S as State

  C->>M: jules_list_sources
  C->>M: jules_create_session(requirePlanApproval=true)
  M->>J: create cloud coding session
  M->>S: record job
  C->>M: jules_list_activities
  C->>M: jules_approve_plan
  C->>M: jules_get_outputs
  M->>S: update job
  C->>C: review patch/PR locally
```

The default plan approval pause is a safety feature. It gives the orchestrator
or user a chance to review the cloud worker plan before code changes proceed.

## State Layout

Runtime state belongs outside Git:

```text
%USERPROFILE%\.dev-triangle
```

Important files and folders:

```text
jobs.json
antigravity-handoffs/
antigravity-results/
patches/
optimization/
```

Repo-local generated folders are ignored:

```text
.dev-triangle-test/
.dev-triangle-report-test/
demo-output/
logs/
```

## Failure Boundaries

Dev Triangle MCP tries to make failures visible instead of mysterious.

Examples:

- If Jules has no key, health checks report key absence.
- If `agy` is missing, CLI detection reports unavailable.
- If Antigravity runs but does not submit a result, the handoff remains
  `AWAITING_RESULT`.
- If a result file lacks `DEV_TRIANGLE_RESULT_READY`, the result is not treated
  as complete.

See [Troubleshooting](TROUBLESHOOTING.md) for practical fixes.

## Provider Direction

The current runtime remains:

```text
Codex -> Jules -> Antigravity
```

Future provider profiles may allow other orchestrators or workers, such as:

```text
Claude -> Gemini CLI -> Antigravity
```

See [Provider Model](PROVIDERS.md) for the planned shape.
