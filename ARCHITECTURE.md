# Legal AI — Architecture

Last Updated: 2026-05-29

## Product Direction

Legal AI is a litigation cognition system.

It is designed to help reason through litigation materials the way an experienced attorney does:

- identify issues
- detect contradictions
- evaluate credibility
- expose attack surfaces
- connect facts to authority
- generate strategy
- produce litigation roadmaps
- assist drafting after analysis

## Core Pipeline

Matter Input
→ Matter Builder
→ Issue Engine
→ Contradiction Engine
→ Entity Graph
→ Credibility Engine
→ Attack Surface Engine
→ Strategy Engine
→ Drafting Engine

## Matter Builder

Purpose:
Build the central matter object from case data, uploaded documents, selected case materials, and attorney-facing analysis outputs.

Responsibilities:
- collect matter documents
- normalize matter data
- pass documents into engines
- assemble outputs for UI
- preserve app.py as thin orchestration layer

## Issue Engine

Purpose:
Identify legally meaningful issues from litigation materials.

Focus:
- procedural issues
- factual disputes
- claim/defense weaknesses
- motion-relevant issues
- attorney-priority issues

## Contradiction Engine

Purpose:
Detect conflicts that matter in litigation.

Current stages:
- v1: simple keyword-based detection
- v2: attorney taxonomy + improved heuristic detector
- planned v3: claim extraction + cross-document comparison

Target contradiction types:
- Position Shift
- Timeline Conflict
- Fact vs Evidence
- Document Conflict
- Witness Conflict
- Procedural Conflict
- Authority Conflict
- Damages Conflict
- Notice Conflict
- Causation Conflict

Target reasoning model:
Party says X
Document says Y
Witness says Z
Timeline shows A
Authority requires B

The contradiction is useful only if it creates litigation value.

## Entity Graph

Purpose:
Track entities and relationships across litigation materials.

Entities may include:
- parties
- witnesses
- attorneys
- courts
- judges
- properties
- contracts
- documents
- events
- dates

Future value:
- connect contradictions to people/documents/events
- support credibility scoring
- support litigation graph view

## Credibility Engine

Purpose:
Identify credibility problems.

Examples:
- inconsistent testimony
- changing explanations
- unsupported assertions
- contradiction with documents
- omission of key facts
- improbable timeline
- self-serving statements

## Attack Surface Engine

Purpose:
Convert detected weaknesses into litigation attack opportunities.

Examples:
- impeachment target
- cross-examination topic
- motion argument
- discovery target
- factual vulnerability
- procedural defect
- evidentiary gap

## Strategy Engine

Purpose:
Turn issues, contradictions, credibility flags, and authority into recommended litigation strategy.

Examples:
- strongest argument
- weakest claim
- best attack sequence
- authority roadmap
- facts to emphasize
- facts to avoid
- discovery needed
- draft outline

## Drafting Engine

Purpose:
Draft only after cognition layer has analyzed the matter.

Drafting should be downstream of:
- issue detection
- contradiction detection
- credibility analysis
- attack surface analysis
- authority mapping
- strategy generation

## Current UI Contract

Contradiction cards currently expect:
- category
- summary
- score
- source_document
- source_snippet

Avoid breaking this contract until a planned UI migration.
