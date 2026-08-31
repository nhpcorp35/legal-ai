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
