# Glossary

Short definitions for terms used in this repo.

## MCP

Model Context Protocol. A standard way for AI clients to discover and call
tools exposed by a local or remote server.

## MCP Server

A process that exposes tools to an AI client. In this repo, the servers speak
JSON-RPC over stdio.

## Control Plane

The part of the system that decides what work exists, who should do it, how to
track it, and when it is complete.

In Dev Triangle MCP, `server.py` is the control-plane server.

## Orchestrator

The main agent the user talks to. The orchestrator understands the task, routes
work, reviews results, and gives the final answer.

Default orchestrator:

```text
Codex
```

## Worker

An agent or service that receives a bounded task from the orchestrator.

Examples:

- Jules as a cloud coding worker.
- Antigravity as a local verifier.

## Verifier

A worker whose main job is to check whether something works.

Antigravity is the default local verifier.

## Handoff

A written task contract from the orchestrator to a worker. A good handoff says:

- What to do.
- Where the project is.
- What context matters.
- What commands to run.
- What counts as done.
- Where to submit the result.

## Closed Loop

A workflow where the orchestrator can create a task, let a worker run, and then
receive the final result automatically through MCP or a result mailbox.

Closed loop does not mean "always successful." It means the status and result
come back to the orchestrator in a trackable way.

## Ledger

The local job record:

```text
%USERPROFILE%\.dev-triangle\jobs.json
```

The ledger stores jobs, handoffs, statuses, notes, timestamps, and result paths.

## Result Mailbox

The file-based return path used for worker results.

Antigravity results are normally written under:

```text
%USERPROFILE%\.dev-triangle\antigravity-results
```

## Result Marker

The text marker that tells Codex the result file is complete:

```text
DEV_TRIANGLE_RESULT_READY
```

If the marker is missing, the result is treated as not ready.

## Report-Only MCP Server

The small worker-facing MCP server:

```text
antigravity_report_server.py
```

It exposes only:

- `dev_triangle_report_health`
- `complete_dev_triangle_handoff`

## `agy`

The Antigravity CLI used for unattended local runs.

The stable route is:

```text
agy --print
```

## Smoke Test

A fast test that proves core plumbing works. The protocol smoke tests use fake
worker paths where needed so CI can run without external credentials.

## Real User-Flow Demo

The local demo script:

```powershell
.\scripts\demo-user-flow.ps1
```

It uses the real local `agy` CLI and proves the Antigravity closed loop on the
user's machine.

## Provider Profile

A future configuration shape that lets the roles be swapped.

Example future profile:

```text
Claude orchestrator -> Gemini CLI code worker -> Antigravity verifier
```

The current stable runtime remains:

```text
Codex -> Jules -> Antigravity
```
