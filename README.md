# Intelligent review of 223-ФЗ technical specifications (ТЗ)

Case: *Интеллектуальная проверка технического задания на закупку товаров, работ, услуг в рамках 223-ФЗ* — find errors,
contestable requirements and risks in a ТЗ, classify them, explain, propose corrections with normative grounds, and
produce a final conclusion. This repository holds the whole pipeline: knowledge-base collectors, the review engine,
an HTTP server with a web UI, and an evaluation harness on the case documents.

## Quick start (Docker)

```bash
tar xzf kb_release_YYYYMMDD.tar.gz   # knowledge base (~60 MB): data/procurement.sqlite, data/index/, kb/  (built with ./make_kb_release.sh)
docker compose up --build -d         # http://localhost:8000  (UI) and /api; first build ~13 min (LibreOffice + llama.cpp)
docker compose logs -f review        # logs
docker compose down                  # stop
```

Optional local LLM: put `Qwen2.5-7B-Instruct-Q4_K_M.gguf` into `./models/` (see `setup_models.sh`); the UI then offers
LLM explanations. Without it the engine runs rules + retrieval only, which is what the evaluation below uses.

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `REVIEW_HOST` / `REVIEW_PORT` | `0.0.0.0` / `8000` | bind address of the server |
| `REVIEW_USE_LLM` | `1` | `0` disables the local LLM even if the model file exists |
| `HF_ENDPOINT` | unset | only for `setup_models.sh`; set to a Hugging Face mirror if huggingface.co is slow |

External services: **none at review time**. The server reads `data/procurement.sqlite`, `data/index/`, `kb/`, `models/`.
Network is used only by the collectors (`collect.py`, `setup_models.sh`, `setup_ru_certs.sh`) when building the KB.

### Local (without Docker)

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
uvicorn server:app --port 8000            # or: python review.py data/case/lift_source.docx --no-llm
python eval_case.py                        # scores against the reviewers' corrections in kb/gold/case_gold.json
```

System packages for legacy formats: `libreoffice`, `p7zip-full`, `file` (all in the Docker image).

## Evaluation on the case documents

`eval_case.py` reconstructs the reviewers' corrections (исходное → итоговое) as gold findings and scores recall on the
originals and false positives on the corrected versions (a finding counts as a false positive only when it is an
ERROR/RISK with disposition FLAGGED; NOTE and "requires manual check" findings are allowed by design).

Current result (rules + retrieval, no LLM), full log in `docs/eval_latest.md`:

| Metric | Result |
|---|---|
| Mandatory reviewer corrections recovered | 10 / 10 (lift 6/6, metrology 4/4) |
| Optional corrections recovered | 4 / 4 (SME-list and per-item commissioning are emitted as manual-review items) |
| False positives on the corrected documents | 0 (remaining findings there are NOTE-level or «требует проверки») |
| Own synthetic services ТЗ (`kb/gold/synthetic_cleaning.docx`, 10 planted problems, different domain) | 9 / 9 mandatory, 2 / 2 optional, correct fragments not flagged |

Everything the engine is unsure about is emitted as *требует проверки* (disposition `INSUFFICIENT_EVIDENCE`) rather than as an error.

Robustness (`review.py` / `POST /api/reviews`): empty, truncated and fake files are rejected with a specific message (HTTP 422);
DOC/RTF/ODT/XLS are converted with LibreOffice; a DOCX renamed to .pdf is detected by content; archives are refused with
«распакуйте». Eight random ТЗ from the corpus (stationery, furniture, cadastral works, lab equipment, medicines) run
without errors in 0.1–0.5 s each.

---

# Knowledge-base collectors (223-ФЗ, Russia)

Collects the *source layer* for the three-analysis design (legal compliance / competition restriction /
technical completeness) into one SQLite database (`data/procurement.sqlite`; schema in `schema.sql`,
Postgres-compatible). Every source is optional: run what works from your network and combine.

## Sources

| Data | Source | Status | Command |
|---|---|---|---|
| 223-ФЗ notices, protocols, clarifications (XML) | `ftp.zakupki.gov.ru` (`free`/`free`), `/out/published/<Region>/<docType>/daily/*.zip` | Unverified; several users report the FTP dead since Jan 2025. Test first: `lftp -u free,free ftp.zakupki.gov.ru` | `eis` |
| Same, via HTML | notice card `/epz/order/notice/notice223/common-info.html?regNumber=` + `documents.html` tab; attachments at `/223/filestore/public/1.0/download/fz223/file.html?uid=` | **Verified live, Nov 2026** (needs RU IP **and** the Russian Trusted Root CA, see below) | `eis-linked` (FAS-referenced notices), `eis-html` (keyword search) |
| Attachments (ТЗ, документация) | links from either of the above | needs RU IP | `attachments` |
| Clause extraction | local PDF/DOCX/XLSX | works | `extract` |
| FAS complaint cases and decisions | `br.fas.gov.ru` case registry (procedure 43021 = «223-ФЗ – жалоба», ~140k cases) and full-text document search (`?type=1&text=`) | **Verified live, Nov 2026** | `fas` |
| 223-ФЗ / 44-ФЗ text, per article and part | consultant.ru (verified), garant.ru (verified, cp1251), pravo.gov.ru iframe pages, direct .docx, RusLawOD corpus | works; see notes | `legal` |
| Historic law editions and all amending acts | [RusLawOD](https://huggingface.co/datasets/irlspbru/RusLawOD), 310k acts scraped from pravo.gov.ru, CC BY-NC | optional, streams 6 GB | part of `legal` |

Not automated (no open bulk access): customer `Положение о закупке` (per-customer in ЕИС), Маркер Интерфакс,
ПРОГОСЗАКАЗ, KonsultantPlus amendment history, manufacturer catalogues, the HSE thesis dataset. The 427-record
CC BY FAS protest dataset mentioned in the design doc could not be located online; ask whoever cited it.

Open-source projects worth reading for ЕИС access (none is a drop-in bulk downloader):
[on-tec/gzcrawler](https://github.com/on-tec/gzcrawler) (PHP, 223-ФЗ notice search),
[chistovod/zakupki-parser](https://github.com/chistovod), [atomno-mcp/mcp-zakupki](https://github.com/atomno-mcp/mcp-zakupki)
(uses official site + commercial APIs; its README is the source of the "FTP broken since Jan 2025" claim),
[irlcode/ruslawod](https://github.com/irlcode/ruslawod) (the legal corpus).

## ЕИС access: certificate, not geography

zakupki.gov.ru serves a certificate chained to the **Russian Trusted Root CA (Минцифры)**, which is not in
certifi or most OS trust stores, so every client fails TLS instantly (`http=000`, `CERTIFICATE_VERIFY_FAILED`).
The FTP host `ftp.zakupki.gov.ru` no longer exists in DNS at all. Fix once:

```bash
./setup_ru_certs.sh      # downloads root+sub CA from gosuslugi, builds certs/ru_bundle.pem, tests the site
```

`procdata/common.py` uses `certs/ru_bundle.pem` automatically when it exists; verification stays on. The site
also refuses foreign IPs (times out through a non-RU VPN), so run the ЕИС steps with the VPN off.

## Run

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python collect.py legal          # consultant + garant + pravo + docx (+ RusLawOD if datasets installed)
python collect.py fas            # case registry (date window in config) + full-text queries, with decisions
python collect.py fas-relabel    # recompute outcome / cited articles after regex changes
python collect.py legal --sources ruslawod   # only the Hugging Face corpus pass
python collect.py eis-linked     # notices referenced by FAS decisions (321 on first run), with attachment links
python collect.py eis-html       # keyword search (config eis.html.search_strings)
python collect.py attachments --limit 50
python collect.py convert        # real formats via file(1), unpack zip/rar/7z, doc/xls/rtf -> docx/xlsx (LibreOffice)
python collect.py extract
python collect.py stats
```

If you already have a `data/procurement.sqlite` from the first version, it is migrated automatically
(new columns and tables are added), but old `legal_rules` rows from the broken pravo run should be deleted:
`sqlite3 data/procurement.sqlite "DELETE FROM legal_rules; DELETE FROM documents WHERE document_type='law';"`

## How the legal merge works

Each source is stored in full (`documents`, `law_texts`, files in `data/legal/`). `legal_rules` is filled per
article (`223ФЗ_ART3`) and per part (`223ФЗ_ART3_P6.1`) in the order listed in `config.yaml`, and a later source
only adds rule ids the earlier ones did not produce, so consultant.ru text wins where available and `source`
records where each row came from. `valid_from`/`valid_to` stay empty: fill them from RusLawOD amendment acts
with a lawyer.

For pravo.gov.ru the law text is in the frame `?doc_itself=&nd=<nd>&page=N` (windows-1251). The `nd` for
223-ФЗ is not set: the RusLawOD pass logs it (`pravogovruNd`), paste it into `pravo_nd`.

## FAS data model

`fas_cases` = one complaint case (number, office, dates, stage, participants with INN and role).
`fas_documents` = each decision / prescription / notice page, with full text and heuristic pre-labels:
`outcome` (UPHELD / PARTIALLY_UPHELD / DISMISSED / NOT_CONSIDERED / UNKNOWN), `legal_basis` (cited
articles), `eis_id_mentioned` (11-digit notice number found in the text, linked to `procurements`).
Treat the heuristics as annotator hints, not ground truth. The raw HTML is kept in `data/fas/html/`.

## What a first run produced (2026-11-03, ~1.5 h, from a Russian home connection)

| Table | Rows | Notes |
|---|---|---|
| `legal_rules` | ~1,600 | 223-ФЗ: 21 articles / 241 parts (consultant). 44-ФЗ: consultant + 25 garant-only articles + 436 RusLawOD-only parts flagged `_other_edition` (older consolidated text, e.g. repealed art. 17) |
| `law_texts` | 82 | 2 laws × consultant/garant/RusLawOD + 20 amending laws of 223-ФЗ and 56 of 44-ФЗ (full text, signing dates) |
| `fas_cases` | 437 | 223-ФЗ complaints: 20 newest registry pages + all of March 2025 (240 cases) |
| `fas_documents` | 692 | 176 dismissed, 81 upheld, 13 partially upheld, 9 not considered, 54 unknown (mostly text only in a PDF attachment), rest notifications |
| linked case → notice number | 223 | join key to ЕИС documents once those are collected |

Known gaps: pravo.gov.ru frame pages time out / return 204 from outside; `fas_documents` attachments (PDF
decisions) are not downloaded yet; ЕИС not yet attempted.

## Phase 2 (same day): freeze, audit, findings, annotation pack

```bash
python collect.py findings            # one row per complaint argument -> fas_findings (regex, unreviewed)
python collect.py amend-dates         # signing + effective dates for the 76 amending laws (7 unambiguous)
python collect.py audit               # docs/audit_<date>.md
python collect.py export-annotation   # data/processed/annotation/annotation_{upheld,dismissed}.jsonl (50 each)
```

- Snapshot of the raw collection: `data/snapshots/procurement_2026-11-03_raw.sqlite`.
- Live schema and row counts for review: `docs/schema_dump.txt`. Audit: `docs/audit_2026-11-03.md`.
- One traced case (decision → challenged requirement → violated provision → rule text): `docs/end_to_end_example.md`.
- `legal_rules.rule_category` ending in `_other_edition` = text from an older consolidated edition; never use as current law.
  `effective_from`/`effective_to` exist but are empty; `law_texts.effective_date` is filled only where the amending act
  states a plain date. Everything else needs a lawyer.
- `fas_findings` fields are regex extractions. `challenged_text` is set only when FAS quotes the requirement («…»);
  otherwise `challenged_text_missing=1`. Outcome per argument comes from "довод … признается (не)обоснованным" when the
  count of verdict sentences matches the count of arguments, else from the document outcome.
- Known labelling error class fixed in relabel: "не обоснованной" split across lines was read as "обоснованной".
  Expect more such cases; the annotation JSONL has an `outcome_correct` field for exactly this check.

## Attachments: formats and conversion

ЕИС filenames are unreliable (DOCX saved as `.doc`, PDFs named `…v.2026`), so `convert` re-detects every file with
`file --mime-type`, resets HTML block pages to pending, unpacks archives with 7z (RAR included) registering each inner
file as its own `documents` row, and converts legacy Office formats with headless LibreOffice. Originals stay on disk;
converted copies live in `converted/` next to them. The ЕИС file server returns 429 after a few hundred downloads;
the fetcher now backs off 60–180 s and the default delay is 3 s.

## Review engine (no network at review time)

Design: `docs/architecture.md`. Three tiers, all local:

| Tier | Module | What it does | Needs |
|---|---|---|---|
| 1 rules | `procdata/checks.py` + `kb/lexicon.json` | units, vague wording, ГОСТ refs, contradictions, missing sections, brand without «или эквивалент», exact dimensions, quantified qualification; scoped to TECHNICAL clauses (contract/legal boilerplate skipped) | nothing |
| 2 ML | `procdata/baseline.py`, `procdata/index.py` | TF-IDF+SVM baselines on weak labels; e5-small embeddings over rule parts and FAS precedents (`review.py --build-index`) | `./setup_models.sh` |
| 2 fine-tuned | `procdata/finetune.py` (`collect.py finetune`) | RuBERT-tiny2 (29M params) clause-role classifier TECHNICAL / CONTRACT / LEGAL, trained on CPU over corpus clauses with weak labels (heuristic + FAS-challenged clauses), split by procurement; used to gate the checks when confident (≥0.8). Trained in 7 min on 16 CPU cores, 11,330 clauses; held-out agreement with the weak labels 0.68 accuracy / 0.72 macro-F1 (`docs/clause_role_metrics.json`). On the case documents it re-scopes 27 contract-condition clauses in the lift ТЗ and leaves the evaluation unchanged (10/10, 0 FP) | `models/rubert-tiny2` |
| 3 LLM | `procdata/explain.py` | Qwen2.5-7B-Instruct Q4 via llama.cpp, evidence-only prompt with the exact matched terms, JSON output; guards: citations must exist in the KB, no «ровно», no invented numbers, bounded length; otherwise the rule explanation/proposal is kept. Runs only for labels where wording matters (brand, exact params, qualification, contradictions, ГОСТ, vague). ~1 min per finding on 16 CPU cores | `models/qwen2.5-7b-instruct-q4_k_m.gguf` |

```bash
./setup_models.sh                                   # once: sklearn, sentence-transformers, llama-cpp, model files (~5 GB)
python review.py --build-index                      # embeddings for rules + precedents -> data/index/
python review.py --procurement 32615808789 --no-llm # review a ТЗ already in the DB (rules + retrieval only)
python review.py path/to/tz.docx                    # review an uploaded file, with LLM explanations
python collect.py baseline                          # tier-2 baselines with per-notice split, reports in models/baselines/
```

Output: `data/reviews/<source>.json` (finding schema from the architecture doc) and a `.md` summary with three
separate sections. On the first linked procurement the rule tier went from 174 raw findings to 8 after scoping
and the lexicon fixes; the brand findings there are real (Polair models without an equivalence clause).

## Feedback and training loop

Every check, finding, reviewer verdict (верно / ложное / другая категория), comment, missed problem and edit is stored
(`reviews`, `review_findings`, `feedback`, `edits`, `model_registry`). The start page has a training panel with counts,
dataset export and retraining. Retraining is gated by the gold suite: a model is promoted only if it loses no mandatory
correction, adds no false positive and downgrades nothing that must stay an error. Details: `docs/training_loop.md`.

```bash
python collect.py training-seed-gold   # gold suite -> feedback rows
python collect.py training-export      # data/training/<stamp>/*.jsonl
python collect.py retrain              # train finding filter, gate, promote/reject, register
```

## Editing loop and training data

In the UI every finding has «Исправить фрагмент»: the fragment opens in an editor (table rows as cells joined by « | »).
You can type the fix, insert the rule's proposal, or ask the local LLM (`POST /api/reviews/{id}/suggest`, evidence-only,
guarded). «Применить и перепроверить» (`POST /api/reviews/{id}/edits`) applies the change to the working copy of the
document and re-runs the whole check in seconds; the finding count before/after is reported and edited fragments are
marked. «Исправленный DOCX» (`GET /api/reviews/{id}/edited.docx`) is the original file with all edits applied.

Every edit is stored in the `edits` table (review, clause, anchor, flagged labels and categories, original text, system
proposal, applied text, method manual/suggestion/llm/llm_edited, whether the re-check cleared the finding, user, time).
`GET /api/edits` returns them, `GET /api/edits?format=jsonl` exports a JSONL file: the supervised dataset for a correction
model (flagged fragment + category → accepted rewrite).

## Server

```bash
pip install fastapi uvicorn python-multipart
uvicorn server:app --host 0.0.0.0 --port 8000        # UI at http://localhost:8000, API under /api
```

`POST /api/reviews` (multipart file, `use_llm`), `POST /api/reviews/by-notice` (`{"notice": "...", "use_llm": false}`),
`GET /api/reviews`, `GET /api/reviews/{id}`, `GET /api/kb`, `GET /api/procurements?q=`, `GET /api/rules/{rule_id}`,
`GET /api/precedents/{finding_id}`. Reviews run in a background thread; the UI polls. The server makes no outbound
requests; it reads `data/procurement.sqlite`, `data/index/` and `models/` only.

## Caveats

* Run ЕИС steps from a Russian IP. Attachments that come back as HTML are block pages (`html_instead_of_file`).
* Rate limits are deliberate (`delay_sec`). br.fas.gov.ru has ~14k pages of 223-ФЗ cases; crawl in date windows.
* Downloaded files are untrusted input: keep them under `data/`, never execute anything from there.
* RusLawOD is CC BY-NC(-SA); fine for the thesis, not for a commercial product.
