# Feedback and training loop

Every interaction with the review UI is stored in `data/procurement.sqlite` and can be turned into training data.
Nothing a model learns reaches users unless it passes the gold-suite gate.

## What is stored

| Table | One row per | Written when |
|---|---|---|
| `reviews` | checked document (file name, SHA-256, contract type, subject, verdict, counts, engine version, KB size) | every check and re-check |
| `review_findings` | finding shown to a reviewer (label, category, severity, disposition, fragment, explanation, proposal, evidence ids, how the clause was scoped) | every check; a re-check marks the previous set `superseded=1`, nothing is deleted |
| `feedback` | reviewer action: `confirm`, `reject`, `wrong_category` (+ correct category), `missed` (+ fragment and category), `comment` | buttons on each finding; clicking an unflagged fragment |
| `edits` | applied correction: original text, system proposal, final text, method (manual / suggestion / llm / llm_edited), whether the re-check cleared the finding | «Применить и перепроверить» |
| `model_registry` | training run: data size, cross-validated metrics, gold scores before/after, status (promoted / rejected / skipped) | «Переобучить» |

Rows with `source='test'` or user ids starting with `synthetic` / `claude-test` are excluded from every export.

## Datasets (`POST /api/training/export`, `python collect.py training-export`)

`data/training/<timestamp>/`:

| File | Use |
|---|---|
| `finding_feedback.jsonl` | finding + fragment → reviewer verdict: trains the false-positive filter; `wrong_category` rows train category correction |
| `missed.jsonl` | fragment + category the system did not flag: new rules, new recall training data |
| `corrections.jsonl` | flagged fragment + category → accepted rewrite, with resolved flag: supervised data for a correction model / LLM fine-tune |
| `comments.jsonl` | free-text reviewer comments for error analysis |
| `manifest.json` | counts by file, verdict and source |

## Retraining (`POST /api/training/retrain`, `python collect.py retrain`)

1. Export the current datasets.
2. If there are at least 20 verdicts and at least 5 `confirm` and 5 `reject`, train the finding filter
   (TF-IDF + logistic regression on label + category + fragment) with stratified cross-validation.
3. **Gate**: run the gold suite (`eval_case.py`) with and without the candidate. Promote only if no mandatory correction is
   lost, no false positive is added, and no mandatory correction is downgraded by the filter.
4. Record the run in `model_registry`; keep the previous active filter if the candidate is rejected.

At review time the promoted filter downgrades a confirmed finding to «требует проверки» when p(reject) ≥ 0.85
(`FILTER_REJECT_THRESHOLD`) and says why in the explanation. It never removes a finding.

`?seed_gold=true` / `python collect.py training-seed-gold` first converts the gold suite into feedback rows
(`source='gold_suite'`): matched corrections become `confirm`, flagged findings on corrected documents become `reject`,
uncovered mandatory corrections become `missed`.

## Verified behaviour (2026-11-13)

| Test | Data | Result |
|---|---|---|
| Real data now | 34 gold confirms, 0 rejects | retrain skipped: «not enough feedback» (correct) |
| Benign synthetic feedback on a DB copy | 106 confirm / 19 reject (reviewers reject formatting notes) | CV macro-F1 0.76, gold 27/27, 0 FP, 27/27 kept → **promoted** |
| Harmful synthetic feedback on a DB copy, threshold 0.6 | reviewers reject real contradictions and warranty errors | gold kept 27 → 17 → **rejected**, previous state restored |

Synthetic test data and models were deleted afterwards.

## Next models this data feeds

- clause-role classifier (`collect.py finetune`): add `wrong_category` / `missed` rows as human labels instead of heuristics;
- category classifier for findings from `wrong_category`;
- correction model: `corrections.jsonl` with `resolved=1` as (input, output) pairs for LoRA fine-tuning of the local LLM.
