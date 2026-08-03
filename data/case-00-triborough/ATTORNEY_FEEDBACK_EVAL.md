# Case-00 Triborough — Attorney-feedback evaluation

Executable evaluation loop over existing Case-00 benchmark artifacts
(`attorney-review-packet-02-live`, `attorney-gold-benchmark-01`, and
`provisional-gold-answers`). Extends the five-dimension attorney gold rubric.
Does **not** invent gold answers, numeric scores, or attorney conclusions.
Provisional material is **never** treated as attorney-approved.

## Command

From the LegalAI repository root:

```bash
python run_case00_attorney_eval.py
```

Equivalent module form:

```bash
python -m case00_attorney_eval.cli
```

Optional flags:

```bash
# Explicit corpus root (default: $CASE00_TRIBOROUGH_ROOT or /app/data/case-00-triborough)
python run_case00_attorney_eval.py --case00-root /app/data/case-00-triborough

# Custom output directory (default: <case00-root>/derived/attorney-feedback-eval)
python run_case00_attorney_eval.py --out /tmp/case00-eval

# Compare a later LegalAI answer set while preserving originals
python run_case00_attorney_eval.py --candidate-answers /path/to/new_answers.json
```

`new_answers.json` shape: `{"Q1": "...", "Q2": "..."}`.

Environment overrides:

- `CASE00_TRIBOROUGH_ROOT` — Case-00 corpus root
- `CASE00_ATTORNEY_EVAL_OUT` — output directory

## Inputs (existing artifacts; not duplicated)

| Artifact | Path |
|---|---|
| Original LegalAI answers | `<case00>/derived/attorney-review-packet-02-live/attorney_review_packet_02.json` (`proposed_answer`) |
| Gold labels / feedback | `<case00>/derived/attorney-gold-benchmark-01/attorney_gold_labels_01.json` |
| Provisional corrected answers | `<case00>/derived/attorney-gold-benchmark-01/provisional-gold-answers/Q*_provisional_gold_answer.md` |
| Final attorney-approved answers | `<case00>/derived/attorney-gold-benchmark-01/attorney-approved-gold-answers/` (optional; absent until expressly approved) |

## Outputs

Default directory (outside git on the executor volume):

```text
/app/data/case-00-triborough/derived/attorney-feedback-eval/
  case00_attorney_feedback_eval.json
  case00_attorney_feedback_eval_summary.txt
```

- **JSON** — deterministic machine-readable per-question records + Case-00 summary counts
- **TXT** — concise human-readable summary

Each question record includes: question id/text, answer version evaluated,
reference-answer status (`none` / `provisional` / `provisional_placeholder` /
`attorney_approved`), feedback labels, scoring dimension states, and missing
information blocking complete scoring. Dimension `score` values remain `null`
unless already present in attorney gold labels.

## Tests

```bash
python -m unittest test_case00_attorney_eval.py -v
```
