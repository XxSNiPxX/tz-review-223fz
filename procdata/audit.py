"""Data-quality audits over the collected database. Prints a report and writes docs/audit_<date>.md."""
import datetime, json, re
from collections import Counter
from pathlib import Path
from .common import ROOT, log

NOTICE_OK = re.compile(r"^3\d{10}$")


def run(db, out_path=None):
    L = []
    def p(s=""): L.append(s)
    q = lambda s, *a: [tuple(r) for r in db.execute(s, a).fetchall()]
    one = lambda s, *a: db.execute(s, a).fetchone()[0]
    p(f"# Data audit {datetime.date.today()}\n")

    p("## Legal rules by edition / source")
    for r in q("SELECT law, source, rule_category, COUNT(*) FROM legal_rules GROUP BY 1,2,3 ORDER BY 1,2,3"):
        p(f"- {r[0]} {r[1]} {r[2]}: {r[3]}")
    cur = one("SELECT COUNT(*) FROM legal_rules WHERE rule_category NOT LIKE '%other_edition%'")
    other = one("SELECT COUNT(*) FROM legal_rules WHERE rule_category LIKE '%other_edition%'")
    p(f"- **current-edition rules (consultant/garant text): {cur}**; other-edition rules: {other}")
    p(f"- rules without source_document_id: {one('SELECT COUNT(*) FROM legal_rules WHERE source_document_id IS NULL')}")
    p(f"- rules with effective_from set: {one('SELECT COUNT(*) FROM legal_rules WHERE effective_from IS NOT NULL')} (expected 0 until amendment pass)")
    p()
    p("## Amending laws (law_texts)")
    for r in q("SELECT law, COUNT(*), MIN(signing_date), MAX(signing_date), SUM(effective_date IS NOT NULL) FROM law_texts WHERE source LIKE 'ruslawod_amend%' GROUP BY 1"):
        p(f"- {r[0]}: {r[1]} amending acts, signed {r[2]}..{r[3]}, with effective_date: {r[4]}")
    p()
    p("## FAS cases")
    p(f"- rows: {one('SELECT COUNT(*) FROM fas_cases')}, distinct case_number: {one('SELECT COUNT(DISTINCT case_number) FROM fas_cases WHERE case_number IS NOT NULL')}, without title (stub from a document page): {one('SELECT COUNT(*) FROM fas_cases WHERE title IS NULL')}")
    dup = q("SELECT case_number, COUNT(*) c FROM fas_cases WHERE case_number IS NOT NULL GROUP BY 1 HAVING c>1")
    p(f"- duplicate case_number values: {len(dup)} {dup[:5]}")
    p(f"- procedure distribution: {q('SELECT procedure, COUNT(*) FROM fas_cases GROUP BY 1 ORDER BY 2 DESC')[:5]}")
    by_oc = q("SELECT COALESCE(outcome,'none'), COUNT(*) FROM fas_cases GROUP BY 1")
    p(f"- by outcome: {by_oc}")
    p()
    p("## FAS documents")
    p(f"- rows: {one('SELECT COUNT(*) FROM fas_documents')}, linked to a case: {one('SELECT COUNT(*) FROM fas_documents WHERE case_id IS NOT NULL')}, orphan (from text search, case unknown): {one('SELECT COUNT(*) FROM fas_documents WHERE case_id IS NULL')}")
    p(f"- by kind: {q('SELECT doc_kind, COUNT(*) FROM fas_documents GROUP BY 1 ORDER BY 2 DESC')}")
    empty = one("SELECT COUNT(*) FROM fas_documents WHERE doc_kind LIKE 'Решение%' AND length(full_text)<300")
    dec_oc = q("SELECT outcome, COUNT(*) FROM fas_documents WHERE doc_kind LIKE 'Решение%' OR title LIKE '%РЕШЕНИЕ%' GROUP BY 1")
    p(f"- decisions with empty text (text only in attachment): {empty}")
    p(f"- decision outcomes: {dec_oc}")
    mult = q("SELECT case_id, COUNT(*) c FROM fas_documents WHERE (doc_kind LIKE 'Решение%') AND case_id IS NOT NULL GROUP BY 1 HAVING c>1")
    p(f"- cases with more than one decision document: {len(mult)} (check: re-issued / several complaints)")
    p()
    p("## Notice-number linkage")
    nums = [r[0] for r in q("SELECT eis_id_mentioned FROM fas_documents WHERE eis_id_mentioned IS NOT NULL")]
    bad = [n for n in nums if not NOTICE_OK.match(n)]
    years = Counter(n[1:3] for n in nums)
    p(f"- documents with a notice number: {len(nums)}, distinct notices: {len(set(nums))}, malformed: {len(bad)}")
    p(f"- notice 'year' digits (positions 2-3, expect 24..26 for recent cases): {dict(sorted(years.items()))}")
    mism = q("SELECT d.doc_uuid, d.eis_id_mentioned, d.doc_date FROM fas_documents d WHERE d.eis_id_mentioned IS NOT NULL AND d.doc_date IS NOT NULL AND CAST(substr(d.eis_id_mentioned,2,2) AS INT) > CAST(substr(d.doc_date,9,2) AS INT)")
    p(f"- notice year later than decision year (impossible -> wrong number picked): {len(mism)} {mism[:3]}")
    p(f"- cases linked to a notice: {one('SELECT COUNT(*) FROM fas_cases WHERE eis_id_mentioned IS NOT NULL')}")
    p()
    p("## Findings")
    nf = one("SELECT COUNT(*) FROM fas_findings"); nq = one("SELECT COUNT(*) FROM fas_findings WHERE challenged_text IS NOT NULL")
    nv = one("SELECT COUNT(*) FROM fas_findings WHERE legal_provision LIKE '%\"violated\": [\"%'")
    p(f"- fas_findings rows: {nf}, with quoted challenged text: {nq}, with violated provision: {nv}")
    p(f"- by requirement_type: {q('SELECT requirement_type, COUNT(*) FROM fas_findings GROUP BY 1 ORDER BY 2 DESC')}")
    p(f"- by outcome: {q('SELECT outcome, COUNT(*) FROM fas_findings GROUP BY 1')}")
    p()
    p("## Provenance")
    p(f"- documents rows: {one('SELECT COUNT(*) FROM documents')}, with storage_path: {one('SELECT COUNT(*) FROM documents WHERE storage_path IS NOT NULL')}, with file_hash: {one('SELECT COUNT(*) FROM documents WHERE file_hash IS NOT NULL')}, with source_url: {one('SELECT COUNT(*) FROM documents WHERE source_url IS NOT NULL')}")
    missing = [r[0] for r in q("SELECT storage_path FROM documents WHERE storage_path IS NOT NULL") if not Path(r[0]).exists()]
    p(f"- storage_path pointing to a missing file: {len(missing)}")
    report = "\n".join(L)
    print(report)
    out = Path(out_path) if out_path else ROOT / "docs" / f"audit_{datetime.date.today()}.md"
    out.parent.mkdir(exist_ok=True); out.write_text(report, encoding="utf-8")
    log.info("audit written to %s", out)


def fill_amendment_dates(db):
    """Signing date comes from the RusLawOD metadata; effective date must be read from the act's final article
    ('Настоящий Федеральный закон вступает в силу ...'). Only the simple, unambiguous patterns are filled
    automatically; everything else is left NULL with the sentence stored for a lawyer."""
    rows = db.execute("SELECT law, source, storage_path FROM law_texts WHERE source LIKE 'ruslawod_amend%'").fetchall()
    n_eff = 0
    for r in rows:
        m = re.search(r"ruslawod_amend_(\d{2})(\d{2})(\d{4})_", r["source"])
        signing = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
        txt = Path(r["storage_path"]).read_text(encoding="utf-8", errors="replace") if Path(r["storage_path"]).exists() else ""
        sent = re.search(r"(Настоящий Федеральный закон вступает в силу[^.]{0,300}\.)", txt)
        eff, src = None, None
        if sent:
            s = sent.group(1)
            d = re.search(r"с (\d{1,2}) (января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря) (\d{4})", s)
            if d and "за исключением" not in s:
                mon = ["января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"].index(d.group(2)) + 1
                eff, src = f"{d.group(3)}-{mon:02d}-{int(d.group(1)):02d}", "text:explicit_date"
            elif re.search(r"со дня (его )?официального опубликования", s) and "за исключением" not in s:
                src = "text:on_publication(date unknown)"
            else:
                src = "text:complex(" + s[:160] + ")"
        db.execute("UPDATE law_texts SET signing_date=?, effective_date=?, effective_date_source=? WHERE law=? AND source=?",
                   (signing, eff, src, r["law"], r["source"]))
        n_eff += eff is not None
    db.commit()
    log.info("amendments: %d rows, %d with an unambiguous effective date", len(rows), n_eff)


def export_annotation(db, out_dir, n_per_class=50):
    """JSONL sample for the first manual annotation exercise: upheld+partial vs dismissed decisions."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    sets = {"upheld": "('UPHELD','PARTIALLY_UPHELD')", "dismissed": "('DISMISSED')"}
    for name, cond in sets.items():
        rows = db.execute(f"""SELECT d.doc_uuid, d.case_id, d.eis_id_mentioned, d.outcome, d.fas_office, d.doc_date, d.source_url, d.full_text
                              FROM fas_documents d WHERE d.outcome IN {cond} AND length(d.full_text) > 2000
                              ORDER BY d.doc_date DESC LIMIT ?""", (n_per_class,)).fetchall()
        path = out_dir / f"annotation_{name}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                finds = db.execute("SELECT argument_no, challenged_text, requirement_type, complainant_argument, customer_argument, fas_reasoning, legal_provision, outcome FROM fas_findings WHERE doc_uuid=? ORDER BY argument_no", (r["doc_uuid"],)).fetchall()
                f.write(json.dumps({
                    "doc_uuid": r["doc_uuid"], "case_id": r["case_id"], "notice": r["eis_id_mentioned"], "doc_outcome_auto": r["outcome"],
                    "office": r["fas_office"], "date": r["doc_date"], "url": r["source_url"],
                    "auto_findings": [dict(x) | {"legal_provision": json.loads(x["legal_provision"])} for x in finds],
                    "annotation": {"outcome_correct": None, "challenged_requirement": "", "requirement_type": "",
                                   "customer_justification": "", "fas_evidence": "", "why_accepted_or_rejected": "",
                                   "competition_indicators": [], "annotator": "", "notes": ""},
                    "full_text": r["full_text"]}, ensure_ascii=False) + "\n")
        log.info("wrote %d records to %s", len(rows), path)
