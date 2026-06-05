# Legal AI — Attorney Knowledge Roadmap

Last Updated: 2026-06-06

## Product Thesis

The moat is litigation cognition.

The goal is not to replace the attorney.

The goal is to help attorneys:

* understand a matter quickly
* verify every important fact
* identify important issues
* identify contradictions
* identify credibility problems
* accelerate research
* accelerate writing
* preserve trust

Attorney Principles:

* Trust > Intelligence
* Verification > Automation
* Every output must be traceable and verifiable
* AI should help identify facts, issues, contradictions, and credibility concerns that attorneys may have overlooked
* AI must never fabricate cases, citations, evidence, testimony, or facts

---

# Attorney Workflow

1. Understand the Matter
2. Verify the Facts
3. Identify Issues
4. Identify Contradictions
5. Assess Credibility
6. Identify Attack Surfaces
7. Develop Strategy
8. Research and Draft

All future development should support this workflow.

---

# Attorney Objective Principle

Before generating output, the system should determine:

"What is the attorney trying to accomplish?"

Different objectives require different outputs.

Examples:

- New lawyer onboarding
- Matter understanding
- Deposition preparation
- Motion practice
- Trial preparation
- Research
- Drafting

The same matter may produce different reports depending on the attorney's objective.

Attorney Feedback (John Cuomo):

"The first question from my software to me should be:
What do you need?
What are you doing?"

Outputs should adapt to the attorney's objective rather than producing a single universal synopsis.

A perfect report for deposition preparation may be completely different from a perfect report for motion practice, trial preparation, research, drafting, or lawyer onboarding.

---

# Phase 1 — Matter Builder

Status: Complete

Purpose:

Create the central matter workspace.

Completed:

* matter ingestion
* document classification
* matter organization

---

# Phase 2 — Matter Understanding Engine

Status: Next

Purpose:

Allow an attorney to understand a matter rapidly.

Planned Outputs:

* matter synopsis
* key facts
* key witnesses
* key documents
* key dates
* procedural posture
* important testimony
* major contradictions
* open questions

Primary Use Case:

New lawyer onboarding.

Primary Attorney Feedback:

A lawyer inheriting a case should be able to understand the matter rapidly without reading every document first.

Future Direction:

Matter Understanding may evolve into a Matter Briefing Engine, where report contents vary based on attorney objective.

Examples:

- New lawyer onboarding
- Deposition preparation
- Motion practice
- Trial preparation
- Research
- Drafting

The first question should not be:

"What report should I generate?"

The first question should be:

"What is the attorney trying to do?"

---

# Phase 3 — Verification & Traceability

Status: Next

Purpose:

Allow attorneys to verify every AI conclusion.

Planned Outputs:

* document references
* page references
* line references
* source snippets
* one-click verification

Attorney Priority:

Highest

Attorney Feedback:

Mistakes destroy credibility.

Every conclusion must be traceable back to source material.

---

# Phase 4 — Issue Engine

Status: Operational

Purpose:

Identify legal and factual issues from matter documents.

---

# Phase 5 — Contradiction Engine

Status: Operational

Purpose:

Attorney-style contradiction detection.

Completed:

* factual disputes
* witness conflicts
* credibility conflicts
* timeline conflicts
* procedural conflicts
* document conflicts
* quantity conflicts
* contradiction scope
* assertion strength
* source traceability
* narratives
* recommendations
* litigation impact

Regression Protected:

* contradiction card payload
* similar case pipeline
* source traceability pipeline
* contradiction scope pipeline
* assertion strength pipeline

Attorney Guidance:

Plaintiff vs Defendant disagreement:

* generally a factual dispute
* not automatically a credibility issue

Same witness changing story:

* major credibility issue
* major impeachment opportunity

Alternative pleading:

* proper legal drafting
* flag separately
* not a contradiction

Information and belief:

* weaker than direct factual assertion
* should not be treated as a fact

Case law for contradictions:

* generally unnecessary
* the contradiction itself is often sufficient

---

# Phase 6 — Credibility Engine

Status: Planned

Purpose:

Identify credibility vulnerabilities.

Examples:

* witness changes story
* sworn statement conflicts
* position shifts
* unsupported factual assertions
* credibility attacks

Attorney Priority:

Very High

---

# Phase 7 — Attack Surface Engine

Status: Planned

Purpose:

Convert weaknesses into litigation opportunities.

Examples:

* impeachment opportunities
* deposition targets
* summary judgment opportunities
* discovery targets
* evidentiary attacks

Attorney Priority:

Very High

---

# Phase 8 — Strategy Engine

Status: Planned

Purpose:

Assist attorney strategic thinking.

Outputs:

* strongest attack surfaces
* strongest defenses
* recommended discovery
* deposition themes
* motion opportunities

Attorney remains the decision maker.

Attorney Feedback:

Some contradictions are best used at deposition.

Some contradictions are best saved for trial.

That determination remains a strategic judgment call.

---

# Planned Extensions

Matter Synopsis Reports

Lawyer Onboarding Reports

Deposition Analysis

Trial Preparation Reports

Alternative Pleading Detection

* flag separately
* not a contradiction

Information & Belief Weighting

Objective-Based Matter Briefing

Different reports for:

- Lawyer onboarding
- Deposition preparation
- Motion practice
- Trial preparation
- Research
- Drafting

---

# Long-Term Research

Litigation Graph

Cross-Matter Knowledge Systems

Litigation Cognition Systems

---

# Session Startup Checklist

Run:

cat PROJECT_STATE.md
cat ARCHITECTURE.md
cat DECISIONS.md
cat attorney_knowledge/ROADMAP.md

Then:

git status
git branch

Then continue from PROJECT_STATE.md.
