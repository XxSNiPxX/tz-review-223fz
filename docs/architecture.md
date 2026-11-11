# Architecture: self-contained review of 223-ФЗ technical specifications

Task (translated from the brief): take a technical specification (ТЗ) for a 223-ФЗ procurement, find errors,
contestable requirements and legal risks, classify each problem, explain why it is a problem, and propose a
correction grounded in legislation, the customer's internal regulation and documentation requirements.

## 1. Design rule: nothing external at review time

The system has two halves with a hard boundary between them.

| Half | Talks to the internet? | When it runs | What it produces |
|---|---|---|---|
| **Knowledge build** (collectors, converters, annotation import) | yes | offline, by a maintainer, versioned | a frozen **knowledge base** release: SQLite + files + vector index |
| **Review engine** (analysis of an incoming ТЗ) | **never** | on demand, per document | findings with evidence, explanations, proposed corrections |

Consequences:

- Every concept the three checks rely on (rules, checklists, precedents, market facts, customer regulations,
  terminology) is a table or file inside the knowledge base, with provenance and a version.
- Models run locally (RuBERT-class encoders, a local Qwen instruct model for explanation). No hosted API.
- A review is reproducible: it records the knowledge-base version and model versions it used.
- If the knowledge base lacks something, the finding says `INSUFFICIENT_EVIDENCE`; the engine does not go and look.

## 2. Component map

```
                 ┌──────────────────────────── KNOWLEDGE BUILD (offline) ────────────────────────────┐
  ЕИС ──► eis_html/attachments ─┐                                                                   │
  br.fas.gov.ru ──► fas_br ─────┤   convert / extract        findings / audit        annotation import│
  consultant/garant/RusLawOD ──►│ ─► clauses, sections  ─► fas_findings, dates  ─► annotations (gold) │
  customer Положения ──► (new) ─┘                                                                   │
                                        │                                                           │
                                        ▼                                                           │
                       ┌─────────────── KNOWLEDGE BASE  (release kb-YYYY.MM.N) ───────────────┐      │
                       │ legal_rules (versioned)   customer_regulations   category_checklists  │      │
                       │ fas_findings + precedent index   market_products/attributes            │      │
                       │ term_lexicon (units, synonyms, vague words)   annotations (gold labels) │      │
                       │ documents/clauses (corpus)   vector index (clauses, precedents, rules)  │      │
                       └──────────────────────────────────────────────────────────────────────┘      │
                 └───────────────────────────────────────────────────────────────────────────────────┘
                                        │ read-only
                                        ▼
  incoming ТЗ ─► ingest ─► clause graph ─► ┌ completeness engine ┐ ─► findings ─► evidence linker ─► explainer ─► report
  (+ metadata:            (sections,        │ competition engine  │     (typed,      (rule / precedent /  (local LLM,   (JSON +
   customer, date,         clauses,         └ compliance engine  ┘      scored)      checklist / market)   constrained)  human UI)
   category, method)       attributes)
```

## 3. The knowledge base: what must exist internally for each check

### 3.1 Compliance check → rule store

| Store | Content | Status in repo |
|---|---|---|
| `legal_rules` | 223-ФЗ (and 44-ФЗ for reference) per article and part, `effective_from/to`, `edition_status` | collected; effective dates still to validate |
| `law_texts` | every edition and amending act with signing/publication/effective dates | 82 texts collected |
| `rule_applicability` | which rule applies to which procurement type/method/customer type and date | table exists, empty: needs legal expert pass |
| `customer_regulations` (**new**) | each customer's Положение о закупке: text, version, approval date, parsed sections (procedure rules, description-of-subject rules, qualification rules) | **not collected**: download per customer from ЕИС for the 321 procurements |
| `doc_requirements` (**new**) | formal checklist of what procurement documentation must contain (223-ФЗ art. 4 part 10, Положение) as structured items | derive from rules + expert |
| `compliance_checks` (**new**) | executable deterministic checks: `check_id`, rule_id, input fields, logic, message template | to write; starts with ~20 checks |

How it is used: deterministic checks run first (dates, mandatory fields, trademark wording, equivalence clause
present, evaluation criteria disclosed). Then retrieval: for each clause, the nearest rule parts by embedding and
by keyword, filtered by `effective_from <= publication_date`. The engine never reads a law from the web.

### 3.2 Competition check → precedent store + market store + justification model

| Store | Content | Status |
|---|---|---|
| `fas_findings` | per-argument findings: challenged text, customer justification, FAS reasoning, provisions, outcome | 420 extracted, unreviewed |
| `precedent_index` (**new**) | embeddings of challenged requirements and FAS reasoning, with outcome and provision labels | build from fas_findings (Qdrant or sqlite-vec, local) |
| `restriction_indicators` (**new**) | taxonomy (BRAND_REFERENCE, NO_EQUIVALENT, EXCESSIVE_PARAMETER, RESTRICTIVE_COMBINATION, RESTRICTIVE_QUALIFICATION, UNJUSTIFIED_CERTIFICATION, JUSTIFICATION_PRESENT, STANDARD_223_PROVISION) with detection patterns and whitelist of standard clauses | define; whitelist prevents false positives on boilerplate |
| `market_products`, `product_attributes` | per category: products, manufacturers, attribute values with units, source and date | tables exist, empty: fill for 1–2 categories by hand/datasheets |
| `justification_patterns` (**new**) | recognised justification types (compatibility, safety, regulatory, operational) and the evidence each requires | define from FAS reasoning |

How it is used: indicator detection on each clause → for flagged clauses, retrieve similar precedents and check
whether a justification is present in the ТЗ → for categories with market data, count how many products satisfy
the parameter set → disposition: NO_INDICATOR / POTENTIAL_RESTRICTION / INSUFFICIENT_EVIDENCE / EXPERT_CONFIRMED.

### 3.3 Completeness check → checklist store + lexicon

| Store | Content | Status |
|---|---|---|
| `category_checklists` | per category (OKPD2-mapped): attributes, importance (REQUIRED/RECOMMENDED/CONDITIONAL), expected type, unit | table exists, empty: expert-defined for chosen categories |
| `term_lexicon` (**new**) | unit synonyms and conversions, vague/non-measurable words, standard designations (ГОСТ pattern), attribute name synonyms in Russian | build from corpus + rules |
| `structure_templates` (**new**) | expected sections of a ТЗ (subject, quantity, characteristics, delivery, warranty, acceptance) by procurement kind (goods/works/services) | derive from the 303 extracted ТЗ |
| `technical_requirements` | extracted attribute/operator/value/unit per clause | table exists; extractor to write |

How it is used: attribute extraction → compare to checklist → missing / vague / unit-less / contradictory /
unverifiable → each finding cites the checklist item and the clause location.

### 3.4 Shared stores

- `documents`, `document_sections`, `clauses`: the corpus (currently 46k clauses from 740 files of 105 procurements),
  used for retrieval of similar wording and for training.
- `annotations`: expert gold labels for all three tasks (schema exists; first 100 decisions exported for annotation).
- `evidence`, `model_findings`: outputs of the engine, kept separate from gold labels.
- `kb_release` (**new**): version id, build date, counts, hashes of source files. Every finding references it.

## 4. Review pipeline for one ТЗ

1. **Ingest**: accept DOCX/PDF/XLSX (and archives), run the same `convert` + `extract` as the corpus, producing
   sections, clauses with offsets, tables. Metadata: customer (INN → its Положение), publication date (→ rule
   edition), procurement method, OKPD2/category (→ checklist).
2. **Clause graph**: clause type (technical / qualification / delivery / evaluation / legal / boilerplate), extracted
   attributes, cross-references between clauses (same attribute in two places → contradiction candidates).
3. **Three engines in parallel**, each emitting typed findings with a confidence and the evidence ids it used.
   Engines are independent; a clause can carry findings from all three.
4. **Evidence linker**: resolves every evidence id to a concrete object (rule part text, precedent, checklist item,
   market product) and refuses findings whose evidence is missing.
5. **Explainer / corrector** (local LLM, constrained): receives one finding plus its evidence objects only, and
   must output: category, explanation that quotes the evidence, a proposed rewording. It may not introduce rules or
   facts absent from the evidence; a post-check verifies every cited rule_id / precedent id exists in the KB.
6. **Report**: JSON (machine) + human view. Three separate sections, never one merged score. Each item is
   clickable to the clause offset and the evidence.

Finding schema (one record per problem):

```
finding_id, review_id, kb_release, clause_id, span_start, span_end,
analysis_type: COMPLETENESS | COMPETITION | COMPLIANCE,
label (from that analysis's taxonomy), severity: ERROR | RISK | NOTE,
disposition: FLAGGED | INSUFFICIENT_EVIDENCE | PASSED,
evidence_ids[], explanation, proposed_text, confidence, method: RULE | RETRIEVAL | MODEL | LLM,
status: AUTO | EXPERT_CONFIRMED | EXPERT_REJECTED
```

## 5. Model stack (all local)

| Role | First choice | Why |
|---|---|---|
| Deterministic checks | Python rules over extracted fields | auditable, no training data needed |
| Clause typing, indicator detection, vague-wording detection | RuBERT / XLM-R fine-tuned on `annotations`; TF-IDF+SVM as baseline | small gold set is enough; fast |
| Attribute extraction | regex + lexicon first, token-classification model later | units/numbers are regular |
| Retrieval | multilingual-e5 or ru-sbert embeddings in Qdrant/sqlite-vec | precedents and rule parts |
| Explanation and corrections | Qwen2.5-Instruct 7B–14B, local, JSON-constrained, evidence-only prompt | explains, never decides |

Evaluation: precision/recall per analysis on held-out procurements, split by customer and period; false-positive
rate on the `STANDARD_223_PROVISION` whitelist is a first-class metric.

## 6. Knowledge-base release process

1. Run collectors (needs RU network + `certs/ru_bundle.pem`), `convert`, `extract`, `findings`, `amend-dates`.
2. Import expert work: annotations, checklists, applicability, effective dates, customer regulations.
3. `audit` must pass; snapshot to `data/snapshots/kb-<version>.sqlite`; build vector index; write `kb_release`.
4. Ship the review engine with that snapshot. Reviews cite the version. Rebuild on a schedule, never live.

## 7. What to build next, in order

1. `customer_regulations` collector (ЕИС, per customer of the 321 procurements) and parser into sections.
2. `compliance_checks`: 20 deterministic checks from 223-ФЗ art. 3 (parts 6, 6.1, 10), art. 4 (part 10) and the
   documentation requirements, each with rule_id and message template.
3. `restriction_indicators` detectors + `STANDARD_223_PROVISION` whitelist, validated against the 71 linked cases.
4. One category end to end (laboratory equipment or IT hardware): checklist, lexicon, 20–30 market products.
5. Precedent index over `fas_findings`; explainer prompt with evidence-only constraint and citation check.
6. Review CLI: `review.py path/to/tz.docx --customer-inn … --date … --category …` → JSON report.


## 8. Data flow for one review and two worked use cases

```
file (.docx/.pdf/.xlsx) ──► ingest.parse ──► Document {sections, tables, attributes, items, fields, clauses}
        │ (fallback: flat text if the file is damaged or unusual)
        ▼
checks.run_checks(clauses)        clause-level: units, vague wording, ГОСТ refs, brand/equivalent, exact dims, qualification
checks_doc.run_doc_checks(doc)    document-level: cross-section contradictions, dimension pairs, warranty basis vs contract
                                   kind, ГОСТ/ГОСТ Р designation (corpus registry), ОКПД2 (classifier: unknown / too generic /
                                   works-vs-goods / missing goods line), kits without composition or to be split, items without
                                   characteristics, out-of-scope national-regime statements, title vs subject, numbers in words
        ▼
resolve_evidence()                rule parts from legal_rules, FAS precedents (hybrid retrieval), lexicon, classifier entries
        ▼ (optional)
explain.explain()                 local Qwen, evidence-only prompt, guarded (citations, no invented numbers, matched terms)
        ▼
report: findings[] (fragment anchor, case category, severity, disposition, explanation, proposal, evidence) + conclusion
```

### Use case 1: works contract, lift replacement (`data/case/lift_source.docx`)

Input: ТЗ with a 34-row attribute table, a works list and a specification line with one ОКПД2 code.
Expected output (all produced by the rule tier, verified by `eval_case.py`):

| Category | Finding | Anchor | Proposal |
|---|---|---|---|
| Противоречие | lift type «пассажирский» in the attribute table vs «грузовой» in the subject and works list | table 1 row 1; section 5 | unify to «грузовой» |
| Противоречие | capacity 300 kg vs 500 kg | table 1 row 3; works table | unify to 500 |
| Противоречие (manual) | door 850×2100 vs 850×2000 | table 1 row 21; works table | confirm single value |
| Гарантия | warranty for works counted from a goods delivery note | section 11 | from КС-2 / КС-3 acts |
| Стандарты (manual) | «ГОСТ 53782-2010» looks like a ГОСТ Р national standard | section 12 | «ГОСТ Р 53782-2010» |
| Код ОКПД 2 | works include supplying a lift but the specification has only a 43.xx works code | specification | add the lift as a goods line (28.22.16.11x) |

Conclusion: "Документ требует доработки до публикации", 4 errors, 2 items for manual review. The corrected version of
the same document yields no ERROR-level findings.

### Use case 2: goods supply, metrology equipment (`data/case/metrology_source.docx`)

Input: 14 items in two tables (one with ОКПД2 codes), a characteristics table, prose requirements in a layout table.
Expected output:

| Category | Finding | Anchor |
|---|---|---|
| Комплектность | «Комплект ручного мерительного инструмента» bundles 10+ different goods under one code: split into positions | items table rows 9, 10, 14 |
| Комплектность | «Электроизмерительный стенд» declared as a kit without an enumerated composition | items table row 1 |
| Код ОКПД 2 (manual) | generic «…190 прочие» codes where exact subclasses exist (e.g. 26.51.33.190 → 26.51.33.142 for a surface plate) | items table |
| Не относится к ТЗ (manual) | statement on national-regime applicability belongs to the procurement documentation | section 4 |

Conclusion: no hard errors, several risks and items for manual review; the corrected 32-item version keeps only
manual-review notes (codes still generic for some items, which the reviewers also left).
