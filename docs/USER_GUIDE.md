# User Guide

This guide explains Dev Triangle MCP for a human who wants to use it, not just
read the source code.

## The Short Version

Dev Triangle MCP lets one main AI agent coordinate other AI coding agents
through stable roles.

The currently validated three-account setup is:

```text
You talk to Codex, the current orchestrator.
Gemini CLI produces a compact context brief and cannot use tools.
Codex reviews the brief.
Claude CLI produces a patch without editing the target repo.
Codex reviews and applies the patch.
The target repo's deterministic suite supplies the final evidence.
Codex gives you the evidence-backed answer.
```

The role-based setup is:

```text
You talk to the orchestrator.
The orchestrator talks to Dev Triangle MCP.
Dev Triangle MCP routes work by role and binding kind.
Agents return briefs, patches, artifacts, or diagnostic reports.
The verifier records machine evidence separately from agent claims.
The orchestrator reviews the result and answers you.
```

The useful part is not merely launching tools. The useful part is that every
task has a record, every dispatch has a destination and artifact path, and the
orchestrator can complete the loop without manual copy and paste.

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

1. The orchestrator creates a job and records the route.
2. The worker receives a narrow task.
3. The role returns a structured brief, patch, artifact, or report.
4. The orchestrator reviews any patch before local mutation.
5. The deterministic suite records exit codes and logs.
6. The ledger accepts `SUCCESS` only when machine evidence passes.

## The Role Model

```mermaid
flowchart LR
  U["User"] -->|request| O["Orchestrator"]
  O -->|job and route| M["Dev Triangle MCP"]
  M --> B["Context Broker"]
  B -->|brief| O
  M --> A["Architect or Cloud Worker"]
  A -->|patch or artifact| G{"Orchestrator review"}
  G -->|reject| O
  G -->|accept| V["Deterministic verification"]
  V --> Q{"Machine checks pass?"}
  Q -->|no| N[("NEEDS_REVIEW")]
  Q -->|yes| S[("SUCCESS and evidence")]
  N --> O
  S --> O
  O -->|final answer| U

  classDef process fill:#ffffff,stroke:#111111,color:#111111,stroke-width:1px;
  classDef decision fill:#eeeeee,stroke:#111111,color:#111111,stroke-width:1px;
  classDef store fill:#ffffff,stroke:#111111,color:#111111,stroke-width:1px;
  class U,O,M,B,A,V process;
  class G,Q decision;
  class N,S store;
  linkStyle default stroke:#111111,stroke-width:1px;
```

**Figure 1. Simplified role, review, and machine-evidence flow.**

See [Role Model](ROLE_MODEL.md) for the tool-agnostic contract.

## The Current Validated Jobs

### Codex: Orchestrator

Codex is the agent you talk to. It should own:

- Understanding your request.
- Inspecting the repository.
- Deciding whether work should stay local or be delegated.
- Dispatching a Context Broker or Architect when useful.
- Using legacy cloud-worker or diagnostician routes when useful.
- Reviewing results from workers.
- Giving you the final answer.

Codex gets the full MCP server because it is the only role that should control
the whole workflow.

### Gemini CLI: Context Broker

The Broker reads the approved source context and returns a structured brief with
source references. The accepted binding uses stdin and the committed deny-all
tool policy. It must not edit files or run tools.

### Claude CLI: Architect

The Architect receives the reviewed brief and identified source files. It
returns a unified diff and test plan. It does not directly edit the target repo.

### Built-in Deterministic Verifier

`run_verification_suite` executes only commands declared by the target repo in
`.dev-triangle/verify.json`. It records stdout, stderr, exit codes, duration, and
`evidenceLevel: machine`. No agent report can replace this evidence.

### Jules: Optional Cloud Worker Compatibility Route

Jules is useful when work is large, repetitive, or PR-shaped.

Good Jules tasks:

- Add tests across many files.
- Migrate an old API.
- Refactor repeated code.
- Upgrade dependency usage.
- Generate a patch or PR for Codex to review.

Jules needs `JULES_API_KEY` in the environment. Dev Triangle MCP does not store
that key.

### Antigravity: Optional Local Diagnostician Compatibility Route

Antigravity is useful when diagnosis depends on your local machine.

Good Antigravity tasks:

- Investigate a failed local smoke test.
- Inspect local project files.
- Verify Docker or local services.
- Inspect whether a UI or CLI appears to work on the actual machine.
- Write a structured report back to Codex.

The stable unattended route is:

```text
agy --print
```

Its output is `agent_asserted`. It may explain why a check failed, but it cannot
make a job `SUCCESS` without the built-in deterministic verifier.

## Why There Are Two MCP Servers

There are two servers because different agents need different permissions.

### `dev_triangle`

This is the main control-plane server.

It can:

- Start Broker-Architect jobs.
- Dispatch context briefs and patches.
- Apply reviewed patches.
- Run deterministic verification suites.
- Describe, activate, modify, and revert provider profiles.
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

A closed loop means the orchestrator can create a task, receive artifacts,
review and apply a patch, run machine verification, and read the final status
without the user manually carrying messages between tools.

For the validated three-account route, the loop is:

```mermaid
sequenceDiagram
  participant User
  participant Codex
  participant MCP as dev_triangle MCP
  participant Gemini as Context Broker
  participant Claude as Architect
  participant Repo as Target repo
  participant Ledger as jobs.json

  User->>Codex: coding task
  Codex->>MCP: start_job
  MCP->>Ledger: persist route and source paths
  Codex->>MCP: dispatch_context_brief
  MCP->>Gemini: redacted allowlisted context
  Gemini-->>Codex: brief and source references
  Codex->>MCP: dispatch_architect after review
  MCP->>Claude: reviewed brief and sources
  Claude-->>Codex: patch path and test plan
  Codex->>MCP: apply_patch after review
  MCP->>Repo: apply on clean tree
  Codex->>MCP: run_verification_suite
  MCP->>Repo: declared allowlisted commands
  Repo-->>MCP: exit codes and logs
  MCP->>Ledger: SUCCESS or NEEDS_REVIEW with evidence
  Codex->>User: final evidence-backed answer
```

**Figure 2. Sequence of the accepted three-account closed loop.**

The result is accepted when:

- The patch was reviewed before application.
- The target tree passed the declared verification suite.
- The ledger contains `evidenceLevel: machine` and exit code 0.
- The job status is `SUCCESS`.

## What The Ledger Does

The ledger is a local JSON file:

```text
%USERPROFILE%\.dev-triangle\jobs.json
```

It stores:

- Broker and Architect dispatch records.
- Patch paths and applied refs.
- Machine-verification commands, outputs, and exit codes.
- Jules jobs and Antigravity handoffs from compatibility routes.
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
Have Jules add the missing tests. Use Antigravity only if local diagnosis is
needed, then run the deterministic verification suite and give me a final
merge/no-merge recommendation with machine evidence.
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

### Switching the whole set at once

Changing roles one at a time is fine for a tweak. When one vendor's quota runs
out you usually want to move everything, so keep a few profiles side by side and
switch between them:

```text
config/providers.claude-heavy.json
config/providers.gemini-heavy.json
config/providers.local-only.json
```

```text
You:  Gemini's quota is gone. Switch to claude-heavy.
Tool: Active profile is now 'claude-heavy' (was 'gemini-heavy').
      Not configured yet: ['cloudWorker']. Say "undo that" to switch back.
```

The choice is written to `config/active-profile.json`, so it survives a server
restart. That file also **wins over** the `DEV_TRIANGLE_PROFILE` environment
variable the installer set — a long-running server can't see an environment
variable that changed after it started, so if the variable won, switching would
appear to do nothing until you restarted. `mcp_health_check` shows which of the
two is actually in force.

**What this deliberately is not:** there is no automatic failover. If a model is
rate-limited, the job fails and tells you which one — it does not quietly
continue on a cheaper model. Automatic downgrade would mean your code quality
drops without the ledger showing anything wrong. Choosing the substitute is
yours.

### Using a CLI you already pay for

A role does not have to be a metered API. If you already have an agent CLI
installed, point a role at it:

```json
"architect": {
  "displayName": "架構師",
  "kind": "cli",
  "command": "claude",
  "args": [],
  "promptArg": "-p",
  "promptVia": "stdin",
  "enabled": true
}
```

For Gemini as a Context Broker, use stdin and load the committed deny-all
policy. `--approval-mode plan` is not sufficient by itself: a live write probe
created a file in plan mode, while the same probe with this policy exposed zero
tools and created nothing.

```json
"contextBroker": {
  "displayName": "Gemini Broker",
  "kind": "cli",
  "command": "gemini",
  "args": [
    "--skip-trust",
    "--approval-mode", "plan",
    "--policy", "<absolute path to config/gemini-broker-deny-all.toml>",
    "--prompt="
  ],
  "promptArg": "",
  "promptVia": "stdin",
  "enabled": true
}
```

The empty `--prompt=` value is intentional. The Gemini CLI requires a prompt
option to enter headless mode, but `-p` without a following value rejects stdin.
Keep the policy path absolute because the CLI runs with the target repository as
its working directory.

`args` is passed through verbatim — if that CLI wants a model flag, put it there.
This project deliberately does not know which flag each CLI uses, because those
CLIs change and this repository would not hear about it.

Two things to expect:

- **No token counts.** A CLI doesn't report them, so the usage rollup shows
  calls but marks tokens unavailable rather than showing zero. Zero would read
  as "this was free"; it isn't, it's coming out of your subscription.
- **`command` cannot be set by talking.** It's file-only, on purpose: with no
  confirmation step on config changes, a request to change an endpoint is a data
  problem, but a request to change *which binary runs* is a code-execution one.

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
- Codex starts the deterministic verifier and reviews its machine evidence.
- The user sees a clear final report.
