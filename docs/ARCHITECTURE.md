# Architecture

Dev Triangle MCP keeps orchestration, worker execution, and result reporting as
separate responsibilities. The architecture is role-based first and
tool-specific second.

The design is intentionally conservative:

```text
One orchestrator sees the full control plane.
Workers receive narrow tasks.
Workers report back through a narrow result surface.
Runtime state stays outside the source tree.
```

## Role-Based Components

```mermaid
flowchart LR
  U(["User"]):::human --> O["Orchestrator<br/>plan, route, review"]:::orchestrator
  O --> M["Dev Triangle MCP<br/>control plane + ledger"]:::mcp

  M --> W["Cloud Code Worker<br/>remote code task"]:::worker
  M --> V["Local Verifier<br/>local validation task"]:::verifier

  W --> O
  V --> R["Report-only MCP<br/>completion channel"]:::report
  R --> S[("Ledger + Result Mailbox")]:::state
  S --> O
  O --> F(["Final answer"]):::human

  classDef human fill:#f8fafc,stroke:#475569,color:#0f172a,stroke-width:1px;
  classDef orchestrator fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px;
  classDef mcp fill:#ede9fe,stroke:#7c3aed,color:#2e1065,stroke-width:2px;
  classDef worker fill:#dcfce7,stroke:#16a34a,color:#052e16,stroke-width:2px;
  classDef verifier fill:#ffedd5,stroke:#ea580c,color:#431407,stroke-width:2px;
  classDef report fill:#fce7f3,stroke:#db2777,color:#500724,stroke-width:2px;
  classDef state fill:#fef9c3,stroke:#ca8a04,color:#422006,stroke-width:2px;
```

## Default Profile Mapping

```mermaid
flowchart LR
  C["Codex<br/>orchestrator"]:::orchestrator --> M["dev_triangle<br/>server.py"]:::mcp
  M --> J["Jules<br/>cloud code worker"]:::worker
  M --> A["Antigravity agy<br/>local verifier"]:::verifier
  J --> C
  A --> R["dev-triangle-report<br/>report server"]:::report
  R --> S[("jobs.json<br/>result markdown")]:::state
  S --> C

  classDef orchestrator fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px;
  classDef mcp fill:#ede9fe,stroke:#7c3aed,color:#2e1065,stroke-width:2px;
  classDef worker fill:#dcfce7,stroke:#16a34a,color:#052e16,stroke-width:2px;
  classDef verifier fill:#ffedd5,stroke:#ea580c,color:#431407,stroke-width:2px;
  classDef report fill:#fce7f3,stroke:#db2777,color:#500724,stroke-width:2px;
  classDef state fill:#fef9c3,stroke:#ca8a04,color:#422006,stroke-width:2px;
```

Only the default profile is implemented and validated today. Other provider
profiles should preserve the same role contracts before they are treated as
stable.

## Responsibilities

| Role or component | Responsibility | Current default | Should not do |
| --- | --- | --- | --- |
| Orchestrator | Understand the user, route work, review results | Codex | Blindly trust worker output |
| Main MCP control plane | Tools, handoffs, ledger, health checks | `server.py` | Expose generic shell execution |
| Cloud Code Worker | Larger edits, repetitive work, PR/patch output | Jules | Receive local secrets |
| Local Verifier | Local checks, environment validation, report writing | Antigravity `agy` | Control the whole workflow |
| Report-only MCP | Accept final worker reports | `antigravity_report_server.py` | Create worker sessions or launch tools |
| Ledger | Track statuses and result paths | `jobs.json` | Store secrets |

## Why Two MCP Servers?

The full server and report server have different trust levels. This is true for
the current default profile and should remain true for future provider profiles.

### Full Server

Name:

```text
dev_triangle
```

File:

```text
server.py
```

This server is for the orchestrator. In the current profile, it can call Jules,
create and run Antigravity handoffs, inspect the ledger, and update jobs.

### Report Server

Name:

```text
dev-triangle-report
```

File:

```text
antigravity_report_server.py
```

This server is for workers and verifiers. It exposes only:

- `dev_triangle_report_health`
- `complete_dev_triangle_handoff`

This keeps worker agents focused. They can submit a result, but they cannot
start unrelated sessions or mutate the whole workflow.

## Local Verifier Closed Loop

The generic local verification loop looks like this:

```mermaid
sequenceDiagram
  participant O as Orchestrator
  participant M as Dev Triangle MCP
  participant V as Local Verifier
  participant R as Report-only MCP
  participant S as Ledger and Mailbox

  O->>M: create local verification handoff
  M->>S: write handoff and ledger entry
  O->>M: run handoff and wait for result
  M->>V: launch verifier with narrow prompt
  V->>R: submit completion report
  R->>S: write result and update status
  M->>S: read completed result
  M->>O: return status and report content
```

The current Antigravity implementation maps to that loop:

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

## Cloud Worker Loop

The generic cloud worker loop looks like this:

```mermaid
sequenceDiagram
  participant O as Orchestrator
  participant M as Dev Triangle MCP
  participant W as Cloud Code Worker
  participant S as Ledger

  O->>M: find connected source
  O->>M: create bounded coding task
  M->>W: create worker session
  M->>S: record job
  O->>M: inspect plan and progress
  O->>M: approve or revise plan
  O->>M: get outputs
  M->>S: update job status
  O->>O: review patch, PR, or artifact
```

The current Jules implementation maps to that loop:

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
