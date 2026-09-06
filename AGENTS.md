# LegalAI Agent Instructions

## Cost-Aware Model Routing

Use GPT-5.6 Luna for low-risk, routine delegated work: repository inspection, status monitoring, formatting, deterministic transformations, boilerplate, focused tests, and clearly scoped fixes.

Start with GPT-5.6 Terra when the task already involves ambiguous multi-file reasoning, architecture, database schemas, public APIs, integrations, persistent data, deployment logic, or non-obvious CI failures. Do not require Luna to fail first.

Escalate Luna to Terra after one clearly diagnosed unsuccessful approach, or immediately when complexity exceeds Luna's lane.

Use GPT-5.6 Sol for LegalAI cognition, legal-reasoning systems, acceptance-policy design, major architecture, high-risk security, or unresolved Terra problems.

Use low reasoning for inspection and monitoring; medium for implementation. Increase reasoning only when task evidence warrants it.

Model escalation is autonomous, but it does not authorize external writes, deployments, private-data transmission, destructive actions, or additional paid generation runs.

Mission Control monitoring and safe status checks may use Luna. Retries must preserve idempotency and must never create duplicate paid runs.

Report models used, escalation reasons, distinct attempts, tests, and whether cheaper routing is appropriate next time.

## LegalAI Execution Integrity Policy

For all LegalAI work, never claim or imply that work has started, is running, is continuing, or is complete unless actual tool or system evidence proves it.

Before execution, silently confirm the target, required tools, necessary inputs, and required authorization. Planning, readiness, or intent do not count as execution.

Use only these four execution states:

- **NOT STARTED** — No execution has occurred. Include the specific reason when relevant.
- **RUNNING** — Execution has actually started. Include concrete observable proof such as a run ID, deployment ID, commit or PR reference, returned tool result, timestamped job state, or equivalent evidence.
- **BLOCKED** — Execution cannot continue. State the specific blocker and the next required action.
- **DONE** — Execution completed successfully and the requested result was verified. Include concrete verification evidence.

Do not substitute vague or hedged language such as "working on it," "continuing," "almost done," "should be deployed," or "basically done" for these states. Never imply unsupported background work when no supported execution mechanism is actually active.

If an execution step fails, report what failed, the observable error or evidence, and the next action. Never minimize or hide failures, and never report a failed attempt as DONE.

For transient failures such as timeouts, temporary 5xx errors, network hiccups, or rate limits, allow up to 2 automatic retries. Each retry must identify the retry number, the previous error, and what changed before retrying, if anything.

For deterministic failures such as bad input, authentication failure, missing secrets, code or build errors, schema mismatches, or other reproducible defects, do not blindly retry. Identify and fix the cause first, then allow 1 fresh retry. If the same deterministic error recurs after a fix attempt, stop and report BLOCKED.

Do not repeatedly retry destructive, security-sensitive, or potentially expensive operations unless they are clearly idempotent and safe. Never enter an unbounded retry loop. Once the applicable retry limit is exhausted, stop and report BLOCKED.

Maintain a concise execution audit trail for LegalAI tasks. For each attempt, preserve the attempt number, action performed, tool or system used, observable result, error if any, fix or change made, and final state. Failed attempts remain part of the record even if a later retry succeeds.

When a task reaches DONE or BLOCKED after retries, or when status is requested, summarize the relevant audit trail so the user can see exactly what happened.

Above all: never confuse intention with execution, and never report RUNNING or DONE without proof.

## Execution Integrity Compliance Rule

All future LegalAI execution and status reporting must comply with the LegalAI Execution Integrity Policy above. Before reporting RUNNING or DONE, confirm that the required evidence exists in the current tool or system state. If the evidence requirement is not satisfied, report NOT STARTED or BLOCKED as appropriate. Any retry must comply with the defined retry limits and audit-trail requirements. DONE is prohibited until the requested outcome has been successfully completed and independently verified.
