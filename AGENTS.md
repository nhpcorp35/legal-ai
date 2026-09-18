# LegalAI Agent Instructions

## Case-00 Source Authority

For Case-00-Triborough, Backblaze B2 is the canonical source for the private
corpus, attorney-feedback packet, acceptance contracts, and durable candidate
artifacts. GitHub contains code only; local checkouts, scratch paths, cached
Markdown, and prior run output are non-canonical working copies.

Before legal analysis, use the canonical B2 object identified by
`data/case-00-triborough/ATTORNEY_FEEDBACK_EVAL.md` and verify its documented
integrity pins. Do not substitute repository search or a local copy for a
canonical B2 retrieval. Use only allowlisted authenticated B2/Bridge access;
never broaden an object key or emit private source material into logs.

Private B2 retrieval is not authorization to transmit evidence to a model
provider, create a paid run, deploy, or write B2. Obtain the applicable
authorization separately and keep runs idempotent.

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

## Daily Attorney-Goal Alignment Check

Every daily LegalAI progress update must explicitly answer: **Did today's verified work move LegalAI toward the attorney-review goals?** State **YES**, **NO**, or **MIXED**.

Support that answer with four short items:

- the attorney-review goal advanced;
- the verified change or result that advanced it;
- the evidence proving the movement (safe commit, test, deployment, run, or reviewed output reference);
- the most important remaining gap or next step.

Do not equate engineering activity, deployment success, or model output with progress toward attorney usefulness unless the verified result improves source completeness, legal/procedural understanding, issue prioritization, litigation cognition, or attorney workflow. If the day's work was maintenance only, say **NO**. If it advanced one goal but exposed or left a material regression, say **MIXED**.

Record this checkpoint in the living PRD's Daily operations log. Keep it GitHub-safe: do not include private source text, credentials, personal attorney details, or privileged feedback.
