# LegalAI PRD (Living)

**Status:** Active  
**Last updated:** 2026-09-06
**Authority:** Canonical product requirements and milestone register for LegalAI.  
**Related (unchanged scopes):** `docs/HAL_CONTROL_ROOM.md` (orchestration contract); `docs/MISSION_CONTROL_OPTIMIZATION_AUTHORITY.md` (Mission Control cost/reliability register).

---

### 2026-09-06 — Case-00 attorney workspace production verification

- Verified the protected Case-00 attorney workflow in production: the
  workspace exposes source search, the verified-record map, a new-review
  question entry point, and compact answered-question history.
- Confirmed a mapped source document opens through the protected PDF relay.
  The relay is bound to the immutable source identity and reads the canonical
  source only through the existing Gateway/Bridge boundary.
- Confirmed the answered-question history displays each fixed Q1–Q5 question
  label and opens its existing review packet; no packet, candidate answer, or
  original source document was modified.
- Confirmed the duplicate-submission guard preserves previously answered
  questions while allowing a distinct new request to be queued.
- Production verification followed LegalAI commit
  `a1e65abf6f42353bea8be23e2209cf1d91bb798e`; Railway deployment
  `7b308c34-2b44-43d1-8a2d-624bbe97ca4a` completed successfully.
- No credentials, authentication configuration, B2 objects, attorney
  communications, or ChatGPT app/OAuth configuration changed.

---

### 2026-09-05 — Source-bound verified workspace citations

- Updated the internal verified-matter workspace to retain the exact
  `source_sha256` for every search result and document-map row.
- Opening a cited PDF now requires that source identity and forwards it to the
  protected Gateway, preventing an identically named document in a future
  supplement ZIP from being confused with the immutable original ZIP.
- Added focused Flask workspace tests for source-bound links and fail-closed
  missing-source behavior. The repository checkout lacks Flask, so those tests
  are queued for Railway’s normal dependency-installed build environment;
  `python -m py_compile app.py` passed locally.
- No case content, B2 objects, attorney packet, recipient, ChatGPT app, or
  OAuth configuration changed.


### 2026-09-04 — Case-00 workspace completeness

- Restored the protected workspace list to all five existing Case-00 review packets (Q1–Q5).
- Packets are read only through the existing Gateway and Bridge from fixed B2 object identities, with size/ETag checks at retrieval and a returned SHA-256 verified by the workspace before display.
- No source documents, candidate content, credentials, access controls, or ChatGPT app configuration changed.

## Product objective

LegalAI augments **litigation cognition and attorney reasoning** — issue framing, posture, credibility, contradiction, strategy, and evidence-grounded analysis — not generic legal search or drafting-as-a-service.

---

## Governing principles

| Principle | Requirement |
|-----------|-------------|
| Probabilistic / systemic law | Model law as contested, posture-dependent systems; avoid false certainty |
| Contradiction & credibility | Surface conflicts and credibility pressure as first-class signals |
| Procedural posture | Anchor analysis to court, stage, and procedural constraints |
| Factual pivots | Identify facts that change outcomes, leverage, or burden |
| Strategy / attack surface | Expose offensive, defensive, discovery, and settlement pressure points |
| Evidence-grounded outputs | Claims must cite recoverable evidence; no unsupported invention |

---

## Scope

**In scope**

- Case-00 attorney-feedback generation/eval loop (code + durable B2 handoff)
- Complaint structure mapping, roadmap attachment, final-prose enforcement
- Thin Unified Gateway for dispatch / status / artifact / storage operations
- Privacy-preserving ops: private corpus and feedback stay off GitHub

**Non-goals**

- Generic legal research chatbot or cite-dump search product
- Unbounded multi-matter drafting without evidence grounding
- Treating provisional gold or technical pass as attorney approval
- Collapsing Bridge, Storage, Mission Control, or artifact services into one deployable
- Committing private corpus, benchmarks, credentials, or attorney feedback to GitHub

---

## Architecture boundaries

| Surface | Boundary |
|---------|----------|
| Unified Gateway | **One thin interface** for dispatch, status, artifact, and storage operations |
| Bridge | Separately deployed; independently healthy and testable |
| Storage | Separately deployed; independently healthy and testable |
| Mission Control | Separately deployed execution engine; independently healthy and testable |
| Artifact services | Separately deployed; independently healthy and testable |

Do not infer topology. Observe authoritative config/deployment metadata (see Mission Control Architecture Verification rule).

---

## Privacy / storage boundaries

| Store | Role |
|-------|------|
| **B2** | Canonical for private corpus and attorney feedback |
| **GitHub** | Code-only (no private matter content) |
| **Working continuity** (local/`/tmp`/executor scratch) | Non-canonical; ephemeral; never proof of durable success |

Four Q1 durable candidate artifacts (B2 object keys, verified):

1. `Q1_candidate_answer.json`
2. `Q1_candidate_answer.md`
3. `generation_manifest.json`
4. `model_input_audit.json`

Workflow entrypoints (code-only): `scripts/run_case00_b2_q1.py`, `scripts/generate_attorney_feedback_candidate.py`, `scripts/run_case00_generate_and_evaluate.py`.

---

## Milestone table

Statuses: **Planned** | **Active** | **Blocked** | **Verified**

| ID | Milestone | Acceptance criteria | Status | Verified evidence |
|----|-----------|---------------------|--------|-------------------|
| M-01 | Unified Gateway ops path | Dispatch, status, artifact, and storage operations succeed through the thin gateway without coupling service internals | Verified | Gateway path proven in production-style ops (dispatch/status/artifact/storage); services remain separately deployable |
| M-02 | Exact review-packet preservation | Review-packet bytes/structure preserved across rebuild/handoff; no silent rewrite of attorney-review inputs | Verified | Preservation checks in rebuild/eval paths; packet treated as immutable input |
| M-03 | B2 bounded retry | Transient B2 reads use bounded retry/backoff; fail-closed on exhaustion; no secret leakage | Verified | `test_b2_read_resilience.py` + B2 helpers in rebuild/upload CLIs |
| M-04 | Q1 structure-map v2 | Generator/rebuild emit/consume `complaint_structure_map.v2` | Verified | `complaint_structure.py` (`SCHEMA_VERSION`); structure-map tests |
| M-05 | Final-prose roadmap enforcement | Candidate final prose must cover canonical roadmap sections; gaps fail closed | Verified | `test_complaint_roadmap_final_prose_phase2.py`; drafting-engine coverage checks |
| M-06 | Stale-context fallback fix | Stale/invalid structure-map schema triggers explicit fallback reason; no silent use of bad context | Verified | `test_complaint_structure_stale_context_fallback.py`; stale/invalid schema reasons |
| M-06b | Acceptance-contract enforcement (generic) | Versioned private acceptance-contract load/authenticate + final-answer validation + production B2 client wiring; Q1 workflow requires external object-key/SHA-256/benchmark pins and fails closed pre-generation on absent/invalid/identity/hash mismatch; audit/manifest expose safe provenance only | Verified (generic) | `acceptance_contract/`; generator + `run_case00_b2_q1.py` wiring; `test_acceptance_contract.py`; `test_acceptance_contract_production_wiring.py`. **Private Q1 contract object provisioning and live validation remain pending** (not claimed here) |
| M-07 | Live Q1 rerun @ pinned commit | Rerun live Q1 workflow at commit `1597db24ec7885b00235520f38d7767819264120`; produce and verify the four canonical B2 artifacts; then compare substance to the **privately held** attorney-approved benchmark (out of band) | **Active** | Pin: `1597db24ec7885b00235520f38d7767819264120`. Technical artifact verification pending live rerun. Substantive compare is private and **not** recorded here. Blocked on private Q1 acceptance-contract provisioning for fail-closed production runs |
| M-08 | Attorney / substantive approval gate | Human attorney acceptance of Q1 substance against approved benchmark | Planned | Blocked on M-07 technical + private substantive compare. **Technical success ≠ attorney/substantive approval**. Existing attorney approval remains limited to the single previously approved review packet; this milestone does **not** claim further attorney approval |

---

## Approval rule (explicit)

**Technical success is not attorney or substantive approval.**

Passing generation, upload `head_object` checks, unit tests, or Mission Control green status only proves engineering criteria. Substantive acceptance requires separate attorney review against the privately held benchmark and must not be claimed from this PRD’s technical milestones alone.

---

## Known risks and current blockers

| Item | Type | Notes |
|------|------|-------|
| M-07 live Q1 rerun not yet verified at pin | Blocker | Must run at `1597db24ec7885b00235520f38d7767819264120` and verify four B2 artifacts |
| Private Q1 acceptance-contract provisioning | Blocker | Generic enforcement/wiring is implemented (M-06b); private contract object + SHA-256 secret pins and live validation are still pending |
| Private benchmark compare | Process | Held privately; do not paste benchmark text, party/attorney identifiers, or legal source contents into GitHub docs or commits |
| Ephemeral scratch mistaken for durable handoff | Risk | `/tmp` and executor workspaces are non-canonical; only verified B2 keys count |
| Mission Control cost/timeout loops | Risk | Tracked in `docs/MISSION_CONTROL_OPTIMIZATION_AUTHORITY.md`; optimization implementation gated on Case-00 attorney approval |
| Contaminating eval with gold during generation | Risk | Generation-only path must not read gold/eval answers |

---

## Next action

1. Provision the private Q1 acceptance-contract object + SHA-256 / benchmark pins in secrets (out of band; do not commit values).
2. Rerun the live Q1 workflow at commit `1597db24ec7885b00235520f38d7767819264120` (or a later main commit that includes M-06b wiring once chosen).
3. Verify the four canonical artifacts on B2 (`head_object` / durable key verification).
4. Compare substance out of band to the privately held attorney-approved benchmark.
5. Record technical evidence (safe commit + technical run IDs only) in this PRD; do **not** mark attorney approval from technical pass alone.

---

## Decision log

| Date | Decision |
|------|----------|
| 2026-08-11 | Establish `docs/LEGALAI_PRD.md` as the living product + milestone authority (code-only; no private artifact contents). |
| 2026-08-11 | Architecture: one thin Unified Gateway; Bridge, Storage, Mission Control, and artifact services stay separately deployed and independently testable. |
| 2026-08-11 | Privacy: B2 canonical for private corpus/feedback; GitHub code-only; working continuity non-canonical. |
| 2026-08-11 | Active milestone M-07: live Q1 at `1597db24ec7885b00235520f38d7767819264120` → four artifacts → private substantive compare. |
| 2026-08-11 | Explicit rule: technical success ≠ attorney/substantive approval. |
| 2026-08-11 | M-06b: generic acceptance-contract enforcement + production B2/Q1 wiring verified in code/tests; private Q1 contract provisioning and live validation remain pending. No additional attorney approval claimed beyond the existing single approved packet. |

---

## Milestone update protocol

Update this PRD **only** when one of the following is true:

1. A milestone is **verified** with recorded evidence (safe commit IDs and technical run IDs only), or
2. A **material blocker / root-cause** changes, or
3. An **architecture or privacy-boundary** decision changes.

**Code missions that affect a milestone must either update this PRD or explicitly state why no PRD update is required.**

Do not update for speculative status, chat memory, or unverified local success. Cite only GitHub-safe commit IDs and technical run IDs — never private benchmark text, party names, attorney names/emails, legal source contents, addresses, credentials, or private artifact contents.


---

## Daily operations log

This is the short, human-readable record of completed work. Update it after
meaningful routine work so Allen can see what changed without needing to approve
each normal code fix. Keep entries GitHub-safe: no private case material,
attorney details, credentials, or source-document text.

### Routine execution authority

Routine diagnosis, code fixes, tests, PRs, merges, deployments, and verification
may proceed without a separate chat approval. Pause only for architecture or
product decisions; new or deleted services/apps/data; authentication, secrets,
billing, or access changes; attorney communications; or non-mechanical legal
judgment.

### 2026-09-03

- Corrected the bounded verified-case source-excerpt extractor after its first
  run returned no matches; merged the one-file fix in
  `nhpcorp35/mission-control` at `074c82a4a29a83a344aefddcd96ecf9d185e3492`.
- Verified the production Bridge deployment completed successfully and produced
  bounded source evidence for the candidate revision.
- Updated the protected verified-case review page with a revised
  source-grounded candidate. The underlying B2 source was not changed, and no
  attorney communication was sent.
- ChatGPT custom-app catalog work remains paused pending the existing Support
  resolution; no new Gateway app was created.


### 2026-09-04

- Completed the protected verified-source review workflow: search returns exact
  cited pages, every result can open its original PDF at the cited page, and
  the review page links directly back to the source search.
- Added keyboard submission for the verified-page search (Enter searches;
  Shift+Enter inserts a line break).
- Made source citations in the protected review packet directly open the
  corresponding original PDF page and added an archived-feedback confirmation
  link after submission.
- Verified the related production deployments completed successfully. The
  verified source, existing review packet, authentication, and ChatGPT app
  configuration were not changed.
- Added the reusable, authenticated verified-matter intake path. It uses
  short-lived direct private-storage uploads, checks the ZIP against every
  manifest-listed PDF byte-for-byte, writes immutable source identity records,
  and creates the bounded search index only after verification.
- Exposed that administrator intake path from the protected workspace. No
  matter data was uploaded or changed as part of this release, and nothing was
  sent to an attorney. Production deployments were verified for
  `8148b0ccf85e5ad84557214af2b09db7bbe0446b`,
  `d47e1f9c3223bbfb63f89a21f376e539501d69c0`, and
  `6e76eaf77984777655a69048b064a18e842965ba`.
- Added focused fail-closed tests for the generic manifest verifier at
  `20ab25b699e608060b2035e00c7f1154a880ea43`: a valid verified ZIP is
  accepted, while a changed PDF or mismatched case identity is rejected.

### 2026-09-05

- Corrected the workspace’s stale legacy matter alias so it resolves to the
  existing canonical verified record instead of displaying a separate
  incomplete placeholder. The immutable source and attorney-review materials
  were not changed.
- Added focused coverage for that alias and verified the workspace source-link
  filename validation. Production deployment completed from
  `e40449b423fc20afd8905ec8ee921febaa8beefc`.
