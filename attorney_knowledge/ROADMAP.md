# Legal AI — Attorney Knowledge Roadmap

Last Updated: 2026-05-29

## Product Thesis

The moat is litigation cognition.

The system should help identify what matters in litigation:
- what facts changed
- what testimony conflicts
- what documents contradict a party
- what procedural defects exist
- what credibility problems exist
- what attack surfaces exist
- what strategy follows

## Phase 1 — Matter Builder

Status: Complete

Purpose:
Create the central matter workspace.

## Phase 2 — Issue Engine

Status: Operational / migrated

Purpose:
Identify legal and factual issues from matter documents.

## Phase 3 — Contradiction Engine v1

Status: Complete

Purpose:
Initial keyword-based contradiction detection.

Limitation:
Too shallow. Detects signals, not true attorney-style contradictions.

## Phase 4 — Contradiction Engine v2

Status: In Progress

Purpose:
Introduce attorney-style contradiction taxonomy and improved heuristic detection.

Completed:
- expanded contradiction categories
- improved detector structure
- preserved UI contract

Next:
- claim extraction
- cross-document comparison
- position shift detection
- document conflict detection
- witness conflict detection

## Phase 5 — Credibility Engine

Status: Planned

Purpose:
Identify credibility problems from contradictions, omissions, timeline problems, and unsupported assertions.

## Phase 6 — Attack Surface Engine

Status: Planned

Purpose:
Convert weaknesses into litigation attack opportunities.

Examples:
- impeachment
- motion argument
- discovery target
- procedural attack
- evidentiary gap

## Phase 7 — Strategy Engine

Status: Planned

Purpose:
Convert issues, contradictions, credibility flags, and attack surfaces into strategy.

Outputs:
- strongest argument
- weakest issue
- recommended roadmap
- draft outline
- authority needs
- factual emphasis

## Phase 8 — Litigation Graph

Status: Planned

Purpose:
Visualize parties, facts, documents, dates, contradictions, and issues as a connected graph.

## Session Startup Checklist

Run:

cat PROJECT_STATE.md
cat ARCHITECTURE.md
cat DECISIONS.md
cat attorney_knowledge/ROADMAP.md

Then run:

git status
git branch

Then continue from PROJECT_STATE.md current workstream.
