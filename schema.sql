-- Core source layer (shared by the three analyses). SQLite-compatible; also valid PostgreSQL
-- if you replace TEXT PRIMARY KEY with appropriate types.

CREATE TABLE IF NOT EXISTS procurements (
  procurement_id      TEXT PRIMARY KEY,        -- internal id = 'EIS223:' || eis_id
  eis_id              TEXT UNIQUE,             -- registrationNumber in ЕИС
  law_type            TEXT NOT NULL,           -- '223-FZ' | '44-FZ'
  customer_id         TEXT,                    -- INN of customer
  customer_name       TEXT,
  procurement_method  TEXT,                    -- purchaseMethodName / purchaseCodeName
  name                TEXT,
  category            TEXT,
  okpd2_code          TEXT,
  initial_price       REAL,
  currency            TEXT,
  publication_date    TEXT,
  submission_deadline TEXT,
  procurement_status  TEXT,
  region              TEXT,
  source_url          TEXT,
  source_archive      TEXT,                    -- FTP zip the XML came from
  raw_xml_path        TEXT,
  ingested_at         TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
  document_id         TEXT PRIMARY KEY,
  procurement_id      TEXT REFERENCES procurements(procurement_id),
  document_type       TEXT,                    -- notice_xml | attachment | protocol_xml | explanation_xml | fas_decision | law
  original_filename   TEXT,
  description         TEXT,
  source_url          TEXT,
  storage_path        TEXT,
  file_hash           TEXT,
  file_format         TEXT,
  publication_date    TEXT,
  document_version    INTEGER DEFAULT 1,
  extraction_status   TEXT DEFAULT 'pending',  -- pending | downloaded | extracted | failed
  error               TEXT
);
CREATE INDEX IF NOT EXISTS ix_documents_proc ON documents(procurement_id);

CREATE TABLE IF NOT EXISTS document_sections (
  section_id          TEXT PRIMARY KEY,
  document_id         TEXT REFERENCES documents(document_id),
  parent_section_id   TEXT,
  section_title       TEXT,
  section_text        TEXT,
  page_start          INTEGER,
  page_end            INTEGER,
  table_reference     TEXT
);

CREATE TABLE IF NOT EXISTS clauses (
  clause_id           TEXT PRIMARY KEY,
  document_id         TEXT REFERENCES documents(document_id),
  section_id          TEXT,
  procurement_id      TEXT,
  clause_text         TEXT NOT NULL,
  normalized_text     TEXT,
  clause_type         TEXT,
  page_number         INTEGER,
  table_id            TEXT,
  position_start      INTEGER,
  position_end        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_clauses_proc ON clauses(procurement_id);

CREATE TABLE IF NOT EXISTS technical_requirements (
  requirement_id      TEXT PRIMARY KEY,
  clause_id           TEXT REFERENCES clauses(clause_id),
  attribute_name      TEXT,
  operator            TEXT,
  value_min           REAL,
  value_max           REAL,
  unit                TEXT,
  standard_reference  TEXT,
  extraction_confidence REAL
);

CREATE TABLE IF NOT EXISTS legal_rules (
  rule_id             TEXT PRIMARY KEY,        -- e.g. 223FZ_ART3
  source_document_id  TEXT REFERENCES documents(document_id),
  law                 TEXT,
  article             TEXT,
  part                TEXT,
  point               TEXT,
  rule_title          TEXT,
  rule_text           TEXT,
  valid_from          TEXT,
  valid_to            TEXT,
  rule_category       TEXT,
  applicability_conditions TEXT
);

CREATE TABLE IF NOT EXISTS rule_applicability (
  rule_id             TEXT REFERENCES legal_rules(rule_id),
  procurement_id      TEXT REFERENCES procurements(procurement_id),
  applicable          INTEGER,
  reason              TEXT,
  verified_by         TEXT,
  verification_date   TEXT,
  PRIMARY KEY (rule_id, procurement_id)
);

CREATE TABLE IF NOT EXISTS fas_cases (
  case_id             TEXT PRIMARY KEY,        -- br.fas.gov.ru uuid
  procurement_id      TEXT,                    -- filled when a ЕИС number is found in the text
  eis_id_mentioned    TEXT,
  decision_document_id TEXT REFERENCES documents(document_id),
  fas_office          TEXT,
  decision_date       TEXT,
  title               TEXT,
  law_type            TEXT,                    -- heuristic: '223-FZ' | '44-FZ' | 'unknown'
  complaint_text      TEXT,
  customer_response   TEXT,
  fas_reasoning       TEXT,
  outcome             TEXT,                    -- heuristic from text: UPHELD | PARTIALLY_UPHELD | DISMISSED | UNKNOWN
  violation_established TEXT,
  legal_basis         TEXT,                    -- JSON list of cited provisions
  appeal_status       TEXT,
  source_url          TEXT,
  full_text           TEXT
);

CREATE TABLE IF NOT EXISTS market_products (
  product_id TEXT PRIMARY KEY, manufacturer_id TEXT, product_name TEXT, product_category TEXT,
  model_number TEXT, source_url TEXT, source_document_id TEXT, valid_from TEXT, valid_to TEXT);
CREATE TABLE IF NOT EXISTS product_attributes (
  product_id TEXT REFERENCES market_products(product_id), attribute_name TEXT, attribute_value TEXT,
  unit TEXT, source_document_id TEXT);
CREATE TABLE IF NOT EXISTS category_checklists (
  category TEXT, checklist_version TEXT, attribute TEXT, importance TEXT, expected_type TEXT, unit TEXT,
  PRIMARY KEY (category, checklist_version, attribute));

CREATE TABLE IF NOT EXISTS annotations (
  annotation_id TEXT PRIMARY KEY, target_type TEXT, target_id TEXT, analysis_type TEXT, label TEXT,
  rationale TEXT, evidence_ids TEXT, annotator_id TEXT, review_status TEXT DEFAULT 'draft',
  annotation_date TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS model_findings (
  finding_id TEXT PRIMARY KEY, procurement_id TEXT, clause_id TEXT, analysis_type TEXT, label TEXT,
  reason TEXT, evidence_ids TEXT, confidence REAL, status TEXT, model_version TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT PRIMARY KEY, evidence_type TEXT, source_document_id TEXT, source_clause_id TEXT,
  source_rule_id TEXT, source_product_id TEXT, page_number INTEGER, quoted_text TEXT, relevance_description TEXT);

-- Added in v2: one row per FAS document (decision / prescription / notice); a case may have several.
CREATE TABLE IF NOT EXISTS fas_documents (
  doc_uuid TEXT PRIMARY KEY, document_id TEXT REFERENCES documents(document_id), case_id TEXT,
  doc_kind TEXT, title TEXT, fas_office TEXT, doc_date TEXT, procedure TEXT, eis_id_mentioned TEXT,
  procurement_id TEXT, law_type TEXT, outcome TEXT, legal_basis TEXT, source_url TEXT, full_text TEXT);
CREATE INDEX IF NOT EXISTS ix_fasdoc_case ON fas_documents(case_id);

-- Every raw law text we managed to obtain, one row per (law, source). legal_rules is the merged view.
CREATE TABLE IF NOT EXISTS law_texts (
  law TEXT, source TEXT, source_url TEXT, storage_path TEXT, edition_note TEXT, fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
  n_articles INTEGER, PRIMARY KEY (law, source));

-- v3: findings extracted from FAS decisions (one row per complaint argument / довод), and legal date fields.
CREATE TABLE IF NOT EXISTS fas_findings (
  finding_id            TEXT PRIMARY KEY,
  case_id               TEXT,
  doc_uuid              TEXT REFERENCES fas_documents(doc_uuid),
  procurement_notice_id TEXT,                 -- 11-digit ЕИС number
  argument_no           INTEGER,              -- order of the довод inside the decision
  challenged_text       TEXT,                 -- exact disputed wording if quoted in the decision, else NULL
  challenged_text_missing INTEGER DEFAULT 1,  -- 1 = must be retrieved from the procurement documentation
  requirement_type      TEXT,                 -- TECHNICAL | QUALIFICATION | DOCUMENTATION | PROCEDURE | EVALUATION | OTHER (heuristic)
  complainant_argument  TEXT,
  customer_argument     TEXT,
  fas_reasoning         TEXT,
  legal_provision       TEXT,                 -- JSON list of provisions FAS found violated / relied on
  outcome               TEXT,                 -- per-argument: UPHELD | DISMISSED | UNKNOWN
  violation_established TEXT,                 -- yes | no | unknown
  extraction_method     TEXT DEFAULT 'regex',
  review_status         TEXT DEFAULT 'unreviewed',
  reviewer_notes        TEXT
);
CREATE INDEX IF NOT EXISTS ix_findings_case ON fas_findings(case_id);

-- v4: human / LLM edits made in the review UI. Training data for the correction model: what was flagged, what the
-- reviewer finally wrote, and whether the re-check cleared the finding.
CREATE TABLE IF NOT EXISTS edits (
  edit_id        TEXT PRIMARY KEY,
  review_id      TEXT,
  source         TEXT,                 -- file name
  clause_id      TEXT,
  anchor         TEXT,
  finding_ids    TEXT,                 -- JSON list
  labels         TEXT,                 -- JSON list of finding labels at the time of the edit
  categories     TEXT,                 -- JSON list of case categories
  original_text  TEXT,
  proposed_text  TEXT,                 -- what the system suggested (rule or LLM), if any
  new_text       TEXT,                 -- what was applied
  method         TEXT,                 -- manual | suggestion | llm | llm_edited
  resolved       INTEGER,              -- 1 if the re-check no longer flags this clause
  findings_before INTEGER,
  findings_after  INTEGER,
  user_id        TEXT,
  created_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_edits_review ON edits(review_id);

-- v5: feedback loop. Everything the reviewer sees and does is stored so it can become training data.
CREATE TABLE IF NOT EXISTS reviews (
  review_id TEXT PRIMARY KEY, source TEXT, file_sha256 TEXT, upload_path TEXT, contract_kind TEXT, subject TEXT,
  n_clauses INTEGER, n_findings INTEGER, errors INTEGER, risks INTEGER, manual INTEGER, verdict TEXT,
  llm_used INTEGER, engine_version TEXT, kb_rules INTEGER, kb_findings INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS review_findings (
  finding_id TEXT PRIMARY KEY, review_id TEXT, clause_id TEXT, anchor TEXT, label TEXT, case_category TEXT, analysis_type TEXT,
  severity TEXT, disposition TEXT, confidence REAL, method TEXT, clause_text TEXT, explanation TEXT, proposed_text TEXT,
  evidence_ids TEXT, scope_method TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, superseded INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_rf_review ON review_findings(review_id);
CREATE TABLE IF NOT EXISTS feedback (
  feedback_id TEXT PRIMARY KEY, review_id TEXT, finding_id TEXT, clause_id TEXT, label TEXT, case_category TEXT,
  verdict TEXT,                 -- confirm | reject | wrong_category | missed | comment
  correct_category TEXT, comment TEXT, clause_text TEXT, user_id TEXT, source TEXT DEFAULT 'ui',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_fb_review ON feedback(review_id);
CREATE TABLE IF NOT EXISTS model_registry (
  model_id TEXT PRIMARY KEY, kind TEXT, path TEXT, trained_at TEXT, n_train INTEGER, metrics TEXT,
  gold_must TEXT, gold_fp INTEGER, status TEXT, notes TEXT);
