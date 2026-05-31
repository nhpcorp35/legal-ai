Roadmap# Legal AI Roadmap
NEXT

Contradiction Engine v2.6
Procedural Conflict Detection

Examples:
- motion served / never served
- notice filed / never filed
- complaint filed / never filed
- service completed / not completed

Output:
- procedural_conflict

v2.7
Evidence vs Assertion
## NOW

### Contradiction Engine v2.4 — Document Extraction

Goal:
Extract structured document claims.

Need:

* document_subject
* document_action
* document_requirement

Examples:

* Lease requires written approval
* Agreement prohibits subletting
* Lease allows pets
* Contract requires notice

Success Criteria:
Document claims become structured objects rather than raw text.

---

## NEXT

### Contradiction Engine v2.5 — Document Conflict Detection

Goal:
Detect contradictions between:

* document vs document
* document vs testimony
* document vs affidavit
* contract vs assertion

Examples:

* Lease requires written approval
* Plaintiff claims verbal approval was sufficient

Output:

* document_conflict

---

## LATER

### Evidence vs Assertion Engine

Goal:
Detect when evidence conflicts with party allegations.

Examples:

* Email confirms notice sent

* Party alleges notice never sent

* Contract requires written approval

* Party alleges verbal approval was enough

Output:

* evidence_conflict
* documentary_conflict

---

## FUTURE

### Litigation Cognition Layer

Goal:
Move beyond contradiction detection into litigation reasoning.

Examples:

* strongest attack points
* credibility attacks
* procedural weaknesses
* burden-of-proof failures
* evidentiary gaps
* strategy recommendations

Attorney Workflow Focus:

* motion practice
* opposition review
* affirmation drafting
* contradiction discovery
* credibility analysis
* litigation strategy support

---

## BACKLOG

* damages conflicts
* authority conflicts
* procedural conflicts
* timeline expansion
* witness credibility scoring
* contradiction ranking improvements
* contradiction clustering
* contradiction visual graph
