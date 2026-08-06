# Case-00 Triborough — Attorney-feedback evaluation

Executable evaluation loop over existing Case-00 benchmark artifacts
(`attorney-review-packet-02-live`, `attorney-gold-benchmark-01`, and
`provisional-gold-answers`). Extends the five-dimension attorney gold rubric.
Does **not** invent gold answers, numeric scores, or attorney conclusions.
Provisional material is **never** treated as attorney-approved.

Also provides deterministic candidate-vs-reference diagnostics (missing facts,
unsupported assertions, party/role mismatches, citation gaps, attorney-label
material-error flags). LLM judge remains disabled.

## Evaluator commands

From the LegalAI repository root:

```bash
python run_case00_attorney_eval.py --help
python -m case00_attorney_eval --help
```

Equivalent module form:

```bash
python -m case00_attorney_eval
python -m case00_attorney_eval.cli
```

Common flags:

```bash
# Explicit corpus root (default: $CASE00_TRIBOROUGH_ROOT or /app/data/case-00-triborough)
python -m case00_attorney_eval --case-root /app/data/case-00-triborough

# Candidate answers file (QID -> text) or generation directory
python -m case00_attorney_eval --candidate-answers /path/to/new_answers.json
python -m case00_attorney_eval --candidate-dir /path/to/q1-candidate-DIR

# Limit to one question; write explicit JSON + human summary paths
python -m case00_attorney_eval \
  --case-root /app/data/case-00-triborough \
  --candidate-dir /tmp/runs/q1-candidate-STAMP \
  --question-id Q1 \
  --json-out /tmp/runs/q1-candidate-STAMP/case00_attorney_feedback_eval.json \
  --summary-out /tmp/runs/q1-candidate-STAMP/case00_attorney_feedback_eval_summary.txt
```

`new_answers.json` shape: `{"Q1": "...", "Q2": "..."}`.

Environment overrides:

- `CASE00_TRIBOROUGH_ROOT` — Case-00 corpus root
- `CASE00_ATTORNEY_EVAL_OUT` — output directory

## One-command generate + evaluate

Local git checkout (commit gate uses `.git` HEAD + `origin/main`):

```bash
python scripts/run_case00_generate_and_evaluate.py \
  --case-root /path/to/case-00-triborough \
  --question-id Q1 \
  --required-commit <full40sha> \
  --output-dir /tmp/case00-runs \
  --authorize-private-evidence-transmission \
    I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER
```

Railway (`legal-ai-executor`, no `.git` required). Set the trusted deployment
metadata that Railway injects, then run the same CLI with the deployed SHA:

```bash
# Railway provides:
#   RAILWAY_GIT_COMMIT_SHA
#   RAILWAY_GIT_REPO_OWNER
#   RAILWAY_GIT_REPO_NAME
#   RAILWAY_GIT_BRANCH
python scripts/run_case00_generate_and_evaluate.py \
  --case-root /app/data/case-00-triborough \
  --question-id Q1 \
  --required-commit "$RAILWAY_GIT_COMMIT_SHA" \
  --output-dir /tmp/case00-runs \
  --authorize-private-evidence-transmission \
    I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER
```

Generation-only (existing CLI) still available:

```bash
python scripts/generate_attorney_feedback_candidate.py \
  --case-root /app/data/case-00-triborough \
  --question-id Q1 \
  --required-commit "$RAILWAY_GIT_COMMIT_SHA" \
  --candidate-output-root /tmp/case00-runs \
  --authorize-private-evidence-transmission \
    I_AUTHORIZE_PRIVATE_EVIDENCE_TRANSMISSION_TO_MODEL_PROVIDER \
  --generation-only
```

Commit verification is fail-closed: normal checkouts must match HEAD and
`origin/main`; Railway runtimes must match `RAILWAY_GIT_*` provenance (commit,
owner `nhpcorp35`, name `legal-ai`, branch `main`). No temporary branches,
clones, or `git update-ref` are required.

Exit codes: `0` success; `2` machine-readable workflow/CLI error JSON; `1`
unexpected failure.

## Inputs (existing artifacts; not duplicated)

| Artifact | Path |
|---|---|
| Original LegalAI answers | `<case00>/derived/attorney-review-packet-02-live/attorney_review_packet_02.json` (`proposed_answer`) |
| Gold labels / feedback | `<case00>/derived/attorney-gold-benchmark-01/attorney_gold_labels_01.json` |
| Provisional corrected answers | `<case00>/derived/attorney-gold-benchmark-01/provisional-gold-answers/Q*_provisional_gold_answer.md` |
| Final attorney-approved answers | `<case00>/derived/attorney-gold-benchmark-01/attorney-approved-gold-answers/` (optional; absent until expressly approved) |

## Outputs

Default evaluator directory (outside git on the executor volume):

```text
/app/data/case-00-triborough/derived/attorney-feedback-eval/
  case00_attorney_feedback_eval.json
  case00_attorney_feedback_eval_summary.txt
```

One-command workflow writes into the generation run directory:

```text
<output-dir>/q1-candidate-<timestamp>/
  Q1_candidate_answer.json
  Q1_candidate_answer.md
  generation_manifest.json
  model_input_audit.json
  case00_attorney_feedback_eval.json
  case00_attorney_feedback_eval_summary.txt
```

- **JSON** — deterministic machine-readable per-question records + Case-00 summary counts + candidate-vs-reference diagnostics
- **TXT** — concise human-readable summary

Each question record includes: question id/text, answer version evaluated,
reference-answer status (`none` / `provisional` / `provisional_placeholder` /
`attorney_approved`), feedback labels, scoring dimension states, missing
information blocking complete scoring, and diagnostic comparison fields.
Dimension `score` values remain `null` unless already present in attorney gold
labels.

## Tests

```bash
python -m unittest \
  test_case00_attorney_eval.py \
  test_case00_attorney_eval_cli.py \
  test_case00_diagnostics.py \
  test_commit_verification.py \
  test_generate_attorney_feedback_candidate.py \
  test_case00_generate_and_evaluate.py \
  -v
```
