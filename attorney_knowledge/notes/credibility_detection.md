# Credibility Detection Heuristics v1

## Core Principle

Credibility often determines litigation outcomes.

A weak witness can weaken a strong claim.

A credible witness can strengthen a weak claim.

## Credibility Red Flags

### Story Changes

The narrative changes over time.

Examples:

* pleading differs from testimony
* affidavit differs from deposition
* discovery response differs from later position

### Missing Corroboration

The witness claims support exists but none is produced.

Examples:

* missing witnesses
* missing records
* missing communications
* missing photographs
* missing video

### Selective Memory

The witness remembers favorable facts but not unfavorable facts.

### Objective Contradiction

Objective evidence conflicts with testimony.

Examples:

* emails
* texts
* photographs
* video
* timestamps
* court filings

### Implausibility

The explanation is technically possible but unlikely.

## Credibility Scoring Factors

* consistency
* corroboration
* documentary support
* timeline accuracy
* motive
* bias
* litigation benefit

## Engine Output

The engine should identify:

* credibility issue
* supporting evidence
* conflicting evidence
* severity
* litigation value
* impeachment potential

## High Value Findings

* perjury indicators
* verification problems
* sworn statement conflicts
* deposition conflicts
* affidavit conflicts
* document conflicts

## Relationship To Contradiction Engine

Every contradiction is not a credibility issue.

Some contradictions directly affect credibility.

Those should receive elevated ranking.

Current contradiction types

factual_dispute
witness_conflict
credibility_conflict
timeline_conflict
date_conflict
quantity_conflict
procedural_conflict
document_conflict
causation_conflict

Current card fields

summary
statement_a
statement_b
source_a
source_b
contradiction_scope
assertion_strength_a
assertion_strength_b
narrative
recommendation
litigation_impact
similar_cases

Current regressions

v6.9.1
v6.9.2
v6.9.3
v6.9.4
v6.9.5

Open attorney questions

alternative pleading
information and belief
credibility weighting
severity weighting
Attorney Feedback — John Cuomo (2026-06-05)

Alternative pleading:
- proper legal drafting
- not a contradiction
- flag separately

Information and belief:
- not a fact
- weaker than direct assertion

Plaintiff vs Defendant:
- generally factual dispute
- not credibility issue

Same witness changing story:
- major credibility issue
- impeachment opportunity

Contradictions:
- do not require case law
- contradiction itself is often sufficient

Trust:
- verification is critical
- document/page/line references are highly valuable