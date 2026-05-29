# Legal AI — Architecture Decisions

Last Updated: 2026-05-29

## 2026-05-29 — Create Project Tracking Files

Decision:
Create persistent project tracker files.

Files:
- PROJECT_STATE.md
- ARCHITECTURE.md
- DECISIONS.md
- attorney_knowledge/ROADMAP.md

Reason:
Important project reasoning was spread across multiple ChatGPT conversations. This caused direction drift when resuming work in new chats.

Impact:
Every future session should begin by reading these files before engine development continues.

---

## 2026-05-29 — Litigation Cognition Is the Core Product

Decision:
Legal AI should focus on litigation cognition, not generic search or generic drafting.

Reason:
Attorney recordings and feedback showed that the highest-value work is how lawyers think through facts, contradictions, credibility, procedure, and strategy.

Impact:
Prioritize:
- Issue Engine
- Contradiction Engine
- Credibility Engine
- Attack Surface Engine
- Strategy Engine
- Litigation Graph

Deprioritize:
- generic legal search
- generic drafting without analysis
- shallow citation summaries

---

## 2026-05-29 — Preserve Existing UI While Upgrading Engines

Decision:
Contradiction Engine upgrades should preserve the existing contradiction card contract.

Current card fields:
- category
- summary
- score
- source_document
- source_snippet

Reason:
The UI is working and should not be broken while backend reasoning improves.

Impact:
Backend detection can improve first.
UI/data model expansion should happen later as a deliberate migration.

---

## 2026-05-29 — Contradiction Engine v2 Taxonomy

Decision:
Expand contradiction categories from placeholder categories to attorney-style litigation categories.

Categories:
- position_shift
- timeline_conflict
- fact_vs_evidence
- document_conflict
- witness_conflict
- procedural_conflict
- authority_conflict
- damages_conflict
- notice_conflict
- causation_conflict

Reason:
These categories better reflect how attorneys locate litigation leverage.

Impact:
Contradiction Engine v2 can now classify more meaningful contradiction signals.

---

## 2026-05-29 — Claim Extraction Comes Before Real Contradiction Reasoning

Decision:
Before cross-document contradiction detection, build a claim extraction layer.

Reason:
Real contradictions require comparing assertions, not just detecting keywords.

Target model:
Document → claims → compare claims → contradiction finding

Impact:
Next planned file:
engines/contradiction_claims.py
