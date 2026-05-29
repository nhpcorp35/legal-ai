# Legal AI — Project State

Last Updated: 2026-05-29

## Current Branch

contradiction-engine-v2

## Current Status

The app is operational.

Current verified state:
- Matter Builder operational
- Issue Engine migrated
- Contradiction Engine integrated
- Entity Graph integrated
- Contradiction UI connected
- App boots clean
- Git clean before current Contradiction Engine v2 work

## Strategic Direction

Legal AI is no longer focused primarily on generic legal search or generic drafting.

The core product direction is litigation cognition:

- issue detection
- contradiction detection
- credibility analysis
- attack surface analysis
- strategy generation
- litigation roadmap generation

## Attorney Workflow Model

Issue
→ Court / Jurisdiction
→ Similar Case
→ Full Docket
→ Complaint
→ Motion
→ Opposition
→ Reply
→ Authority
→ Roadmap
→ Draft

## Completed Engines / Systems

- Matter Builder
- Issue Engine
- Contradiction Engine v1
- Contradiction Engine v2 taxonomy
- Entity Graph
- Contradiction UI wiring
- Attorney Knowledge Repository structure

## Attorney Knowledge Repository

attorney_knowledge/
├── emails/
├── examples/
├── flowcharts/
├── transcripts/
└── notes/

Completed notes:
- litigation_workflow.md
- attorney_heuristics.md
- contradiction_detection.md
- credibility_detection.md
- attack_surface.md
- strategy_engine.md

## Current Workstream

Contradiction Engine v2

Goal:
Move from placeholder keyword detection toward attorney-style contradiction analysis.

Current completed work:
- Expanded contradiction taxonomy:
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
- Improved heuristic detector while preserving existing UI contract

Current UI contract:
Contradiction reporter expects:
- category
- summary
- score
- source.filename
- source.source_snippet

## Next Planned Steps

1. Create contradiction claim extraction layer
2. Extract assertion-like sentences from documents
3. Compare claims across documents
4. Detect position shifts
5. Detect witness conflicts
6. Detect document conflicts
7. Detect fact vs evidence conflicts
8. Add litigation value language
9. Preserve existing UI until data model upgrade is safe

## Working Rules

- Full files only
- Use /tmp file creation
- Include mv command every time
- One migration step at a time
- Test after every file change
- Commit at safe checkpoints
- Preserve working app at all times
- Do not touch UI unless necessary
- Do not expand scope without updating this file

## Resume Command

When starting a new chat, run:

cat PROJECT_STATE.md
cat ARCHITECTURE.md
cat DECISIONS.md
cat attorney_knowledge/ROADMAP.md
