# User Guide

This guide explains Dev Triangle MCP for a human who wants to use it, not just
read the source code.

## The Short Version

Dev Triangle MCP lets one main AI agent coordinate other AI coding agents
through stable roles.

The default setup is:

```text
You talk to Codex.
Codex talks to Dev Triangle MCP.
Dev Triangle MCP can send work to Jules.
Dev Triangle MCP can send local validation to Antigravity.
Workers report back through a controlled result channel.
Codex gives you the final answer.
```

The role-based setup is:

```text
You talk to the orchestrator.
The orchestrator talks to Dev Triangle MCP.
Dev Triangle MCP routes work to a worker or verifier.
The worker reports back through a narrow return channel.
The orchestrator reviews the result and answers you.
```

The useful part is not merely launching tools. The useful part is that every
task has a record, every handoff has a result path, and Codex can wait for the
worker to finish instead of relying on manual copy and paste.

## What Problem It Solves

Without a control plane, a multi-agent workflow often looks like this:

1. You ask one AI to make a plan.
2. You copy the plan into another AI.
3. You wait.
4. You copy the result back.
5. You ask another AI to verify it.
6. You forget which output belongs to which task.
7. You manually decide whether the result is done.

Dev Triangle MCP turns that into a trackable loop:

1. Codex creates a job or handoff.
2. The worker receives a narrow task.
3. The worker writes a structured result.
4. Codex reads the result from the ledger.
5. Codex decides the next step.

## The Role Model

```mermaid
flowchart LR
  U(["User"]):::human --> O["Orchestrator<br/>understands and reviews"]:::orchestrator
  O --> M["Dev Triangle MCP<br/>routes and records"]:::mcp
  M --> W["Worker<br/>code output"]:::worker
  M --> V["Verifier<br/>local validation"]:::verifier
  W --> O
  V --> R["Reporter<br/>final result only"]:::report
  R --> S[("Ledger + result mailbox")]:::state
  S --> O

  classDef human fill:#f8fafc,stroke:#475569,color:#0f172a,stroke-width:1px;
  classDef orchestrator fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px;
  classDef mcp fill:#ede9fe,stroke:#7c3aed,color:#2e1065,stroke-width:2px;
  classDef worker fill:#dcfce7,stroke:#16a34a,color:#052e16,stroke-width:2px;
  classDef verifier fill:#ffedd5,stroke:#ea580c,color:#431407,stroke-width:2px;
  classDef report fill:#fce7f3,stroke:#db2777,color:#500724,stroke-width:2px;
  classDef state fill:#fef9c3,stroke:#ca8a04,color:#422006,stroke-width:2px;
```

See [Role Model](ROLE_MODEL.md) for the tool-agnostic contract.

## The Default Jobs

### Codex: Orchestrator

Codex is the agent you talk to. It should own:

- Understanding your request.
- Inspecting the repository.
- Deciding whether work should stay local or be delegated.
- Creating Jules sessions when useful.
- Creating Antigravity handoffs when local validation is useful.
- Reviewing results from workers.
- Giving you the final answer.

Codex gets the full MCP server because it is the only role that should control
the whole workflow.

### Jules: Cloud Coding Worker

Jules is useful when work is large, repetitive, or PR-shaped.

Good Jules tasks:

- Add tests across many files.
- Migrate an old API.
- Refactor repeated code.
- Upgrade dependency usage.
- Generate a patch or PR for Codex to review.

Jules needs `JULES_API_KEY` in the environment. Dev Triangle MCP does not store
that key.

### Antigravity: Local Verifier

Antigravity is useful when work depends on your local machine.

Good Antigravity tasks:

- Run local smoke tests.
- Inspect local project files.
- Verify Docker or local services.
- Confirm a UI or CLI works on the actual machine.
- Write a structured report back to Codex.

The stable unattended route is:

```text
agy --print
```

The older IDE chat launch route can open a UI, but it is not the preferred
closed-loop path for unattended runs.

## Why There Are Two MCP Servers

There are two servers because different agents need different permissions.

### `dev_triangle`

This is the main control-plane server.

It can:

- Call Jules.
- Create Antigravity handoffs.
- Launch Antigravity.
- Read and write the local ledger.
- Check health.

Only the orchestrator should see this server.

### `dev-triangle-report`

This is the report-only server.

It can:

- Say whether the report server is healthy.
- Accept a final handoff report.

Worker agents can see this server because it is intentionally tiny. It does not
let them create more cloud sessions, modify unrelated jobs, or run arbitrary
commands.

## What A Closed Loop Means

A closed loop means Codex can create a task, wait for the worker, and read the
final result without the user manually carrying messages between tools.

For Antigravity, the loop is:

```mermaid
sequenceDiagram
  participant User
  participant Codex
  participant MCP as dev_triangle MCP
  participant AG as Antigravity agy
  participant Report as dev-triangle-report MCP
  participant Ledger as jobs.json + result file

  User->>Codex: "Verify this project locally"
  Codex->>MCP: create_antigravity_handoff
  MCP->>Ledger: write handoff markdown
  Codex->>MCP: run_antigravity_handoff
  MCP->>AG: agy --print with handoff prompt
  AG->>Report: complete_dev_triangle_handoff
  Report->>Ledger: write result markdown + update status
  AG-->>MCP: stdout may be empty
  MCP->>Ledger: recover marker from Antigravity conversation DB if needed
  Codex->>MCP: antigravity_get_result
  MCP->>Codex: status, result path, report content
  Codex->>User: final explanation
```

The result is considered ready when:

- The handoff status is `COMPLETED`.
- The result file exists.
- The result contains `DEV_TRIANGLE_RESULT_READY`.

## What The Ledger Does

The ledger is a local JSON file:

```text
%USERPROFILE%\.dev-triangle\jobs.json
```

It stores:

- Jules jobs.
- Antigravity handoffs.
- Statuses.
- Timestamps.
- Result paths.
- Notes.

This gives the workflow memory without committing runtime data to Git.

## How To Decide The Route

Use this practical rule:

| Situation | Best route |
| --- | --- |
| Tiny fix, clear local file | Codex directly |
| Many repeated edits | Jules |
| Needs a PR or cloud patch | Jules |
| Needs local commands or local services | Antigravity |
| Needs both broad code work and local verification | Jules first, Antigravity second |
| Needs sensitive local secrets | Usually keep it local; do not send secrets to workers |

## Example Prompts

Small local task:

```text
Use Dev Triangle MCP only if needed. Inspect this repo and add a smoke test for
the command parser. If the change is small, keep it local and verify it here.
```

Jules-shaped task:

```text
Use Dev Triangle MCP and create a Jules task if appropriate.

Goal:
Migrate all legacy config readers to the new settings loader and open a PR or
return a patch. Require plan approval before code changes.
```

Antigravity-shaped task:

```text
Use Dev Triangle MCP to create an Antigravity handoff.

Goal:
Run the local Docker smoke test, inspect the generated logs, and submit a final
report through dev-triangle-report.
```

Full triangle task:

```text
Use Dev Triangle MCP for this project.

Goal:
Have Jules add the missing tests, then have Antigravity run local verification,
then give me a final merge/no-merge recommendation.
```

## Changing Models By Talking

You never have to open a JSON file to change which model a role uses. Tell the
orchestrator and it calls `profile_set_role` for you.

```text
You:  Switch the architect to <model id>.
Tool: architect: {'model': ''} -> {'model': '<model id>'}. This is now permanent.
      Tell me if you only wanted it for this one job.
      Say "undo that" to reverse it.
```

Four things this deliberately does, and why.

**It never asks you to confirm.** Configuring your own tools is your business.
What replaces the confirmation is that the change is always reported back, even
when you did not ask for a report. If you ever see a change summary for
something you did not request, that is the signal — something in a repo file or
an error log talked the orchestrator into it. Say "undo that".

**It refuses to take your key.**

```text
You:  My key is ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Tool: Refusing to write apiKeyEnv: it contains something that matches
      ['github_pat']. Do not paste a key into the conversation. Set it in an
      environment variable of your own choosing, then tell me that variable's
      NAME. Nothing was written.
```

Nothing is written when this happens. The reason for the refusal is that a key
said out loud ends up in three places at once — the conversation log, the MCP
transport, and the config file — and this project can only ever clean up the
third. Blocking at the write is already late; it is blocked loudly so you know
that message needs dealing with.

Do this instead:

```powershell
$env:MY_ARCHITECT_KEY = "..."
```

```text
You:  The architect's key is in MY_ARCHITECT_KEY.
```

**It will not invent a model id.** Ask for "the newest one" and, if the provider
can list its models, you get the real list back rather than a plausible-looking
guess:

```text
Tool: Model 'the-newest-one-probably' is not offered by that provider.
      Closest matches: [...]. Nothing was written.
```

If the provider cannot list its models, the id is written but recorded as
unverified, and `profile_describe` keeps showing it that way. "Could not check"
is never quietly upgraded to "checked".

**It only knows seven roles.** Ask for an eighth and it says so, rather than
writing a field nothing will ever read:

```text
You:  Add a reviewer role.
Tool: Unknown role 'reviewer'. This project has exactly these seven:
      ['orchestrator', 'contextBroker', 'architect', 'cloudWorker', 'verifier',
       'diagnostician', 'reporter']
```

### Undoing

```text
You:  Undo that.
Tool: Reverted 1 configuration change(s) on profile 'example'.
```

The undo is itself recorded, so the change log stays complete in both
directions.

### Seeing what is bound right now

```text
You:  What is each role using?
```

`profile_describe` answers with every slot, which ones are unconfigured, which
model ids are unverified, which roles share a model, and the recent change
history including the words that caused each change.

That last part is the point of recording your own phrasing: three weeks later,
"why was it using that model" has an answer.

## What To Check When It Feels Stuck

First run:

```powershell
.\scripts\doctor.ps1
```

Then check the ledger:

```text
%USERPROFILE%\.dev-triangle\jobs.json
```

Then check the result directory:

```text
%USERPROFILE%\.dev-triangle\antigravity-results
```

If a handoff is stuck at `AWAITING_RESULT`, the worker launched but did not
write the result marker. See [Troubleshooting](TROUBLESHOOTING.md).

If `agy --print` exits with empty stdout, do not treat stdout as the source of
truth. The handoff is complete only when the report MCP, result file marker, or
recoverable Antigravity conversation DB marker proves completion.

## Human Expectations

Dev Triangle MCP is a coordination layer. It should make the workflow easier to
run and easier to audit. It does not remove the need for code review, tests, or
human judgment when the change matters.

The safest default is:

- Codex decides.
- Workers do narrow jobs.
- Results return through MCP.
- Codex verifies.
- The user sees a clear final report.
