#!/usr/bin/env python3
"""Review one technical specification (ТЗ) against the internal knowledge base. No network access.

  python review.py path/to/tz.docx [--category LAPTOP] [--date 2025-03-01] [--no-llm] [--out report.json]
  python review.py --procurement 32515315180          # review a ТЗ already in the database
  python review.py --build-index                       # (re)build the local retrieval index from the KB
"""
import argparse, json, logging, re, sys, datetime
from pathlib import Path
from procdata.common import load_config, open_db, log, ROOT
from procdata import checks, extract_text, index as kb_index, explain, ingest, checks_doc, report as rep


CASE_CAT = {"COMPETITION": "COMPETITION_RESTRICTION", "COMPLETENESS": "COMPLETENESS", "COMPLIANCE": "STANDARDS"}
LABEL_CAT = {"INCOMPLETE_STANDARD_REFERENCE": "STANDARDS", "CONTRADICTORY_REQUIREMENTS": "CONTRADICTION", "MISSING_UNIT": "INCORRECT_CHARACTERISTIC",
             "VAGUE_REQUIREMENT": "INCORRECT_CHARACTERISTIC", "MISSING_WARRANTY_DETAIL": "WARRANTY"}


def categorize(f):
    f.setdefault("case_category", LABEL_CAT.get(f["label"], CASE_CAT.get(f["analysis_type"], "COMPLETENESS")))
    return f


def analyze(clauses, doc=None):
    """All deterministic findings for a document: clause-level checks + document-level checks (when structured)."""
    findings = [categorize(f) for f in checks.run_checks(clauses)]
    if doc is not None:
        # a goods list with many items legitimately repeats "не менее N" per item: clause-level contradictions are noise there
        if len(doc.get("items") or []) >= 2:
            findings = [f for f in findings if f["label"] != "CONTRADICTORY_REQUIREMENTS"]
        findings += [categorize(f) for f in checks_doc.run_doc_checks(doc)]
    return findings


def conclusion(findings, doc=None):
    """Final summary block required by the case: counts per category, top risks, what needs manual review."""
    by_cat = {}
    for f in findings: by_cat.setdefault(f["case_category"], []).append(f)
    errors = [f for f in findings if f["severity"] == "ERROR" and f["disposition"] == "FLAGGED"]
    risks = [f for f in findings if f["severity"] == "RISK" and f["disposition"] == "FLAGGED"]
    manual = [f for f in findings if f["disposition"] == "INSUFFICIENT_EVIDENCE"]
    verdict = ("Документ требует доработки до публикации" if errors else "Существенных ошибок не выявлено; есть риски для ручной проверки" if risks or manual else "Замечаний не выявлено")
    return {"verdict": verdict, "errors": len(errors), "risks": len(risks), "manual_review": len(manual), "notes": sum(f["severity"] == "NOTE" for f in findings),
            "by_category": {k: len(v) for k, v in by_cat.items()},
            "top": [{"category": f["case_category"], "label": f["label"], "summary": f["explanation"][:160], "anchor": (f.get("anchors") or [None])[0]} for f in (errors + risks)[:8]],
            "document": ({"subject": doc["fields"].get("subject"), "contract_kind": doc["fields"].get("contract_kind"), "customer": doc["fields"].get("customer"),
                          "sections": doc["fields"].get("n_sections"), "tables": doc["fields"].get("n_tables"), "items": doc["fields"].get("n_items"),
                          "okpd2_codes": doc["fields"].get("okpd2_codes"), "standards": doc["fields"].get("standards")} if doc else None)}


class UnreadableFile(Exception):
    pass


def prepare_file(path: Path) -> Path:
    """Return a path the readers can open: detect the real type, convert legacy Office formats, reject the rest with a clear message."""
    from procdata import convert as cv
    if not path.exists() or path.stat().st_size == 0:
        raise UnreadableFile("файл пустой")
    fmt = cv.MIME_EXT.get(cv.mime(path))
    ext = path.suffix.lower()
    if fmt is None:                                        # file(1) says octet-stream for some generated OOXML: sniff the container
        import zipfile
        try:
            if zipfile.is_zipfile(path):
                names = set(zipfile.ZipFile(path).namelist())
                fmt = "DOCX" if "word/document.xml" in names else "XLSX" if "xl/workbook.xml" in names else "ZIP"
            elif path.read_bytes()[:5] == b"%PDF-":
                fmt = "PDF"
        except Exception:  # noqa
            fmt = None
    if fmt in ("DOCX", "PDF", "XLSX"):
        want = "." + fmt.lower()
        if ext != want:                                   # e.g. a DOCX saved as .pdf
            fixed = path.with_suffix(want); fixed.write_bytes(path.read_bytes()); return fixed
        return path
    if fmt in cv.CONVERT:                                  # DOC / RTF / ODT / XLS / ODS via LibreOffice
        out = cv._soffice(path, cv.CONVERT[fmt], path.parent / "converted")
        if out: return out
        raise UnreadableFile(f"не удалось конвертировать {fmt} через LibreOffice")
    if fmt in cv.ARCHIVE:
        raise UnreadableFile("это архив: распакуйте и загрузите файл ТЗ отдельно")
    if fmt == "HTML":
        raise UnreadableFile("это HTML-страница, а не документ")
    raise UnreadableFile(f"формат не распознан ({cv.mime(path) or 'unknown'}); поддерживаются DOCX, DOC, RTF, ODT, PDF, XLSX, XLS")


def clauses_from_file(path: Path):
    reader = extract_text.READERS.get(path.suffix.lower())
    if not reader:
        raise UnreadableFile(f"unsupported format {path.suffix}")
    out = []
    for page_no, text in reader(path):
        for a, b, chunk in extract_text.split_clauses(text):
            out.append({"clause_id": f"{path.stem}:p{page_no}_{a}", "procurement_id": None, "clause_text": chunk,
                        "normalized_text": re.sub(r"\s+", " ", chunk).lower(), "page_number": page_no, "position_start": a, "position_end": b})
    return out


def clauses_from_db(db, reg):
    rows = db.execute("SELECT c.*, d.original_filename AS document_name FROM clauses c JOIN documents d ON d.document_id=c.document_id "
                      "WHERE c.procurement_id=? ORDER BY d.document_id, c.page_number, c.position_start", (f"EIS223:{reg}",)).fetchall()
    return [dict(r) for r in rows]


PREC_MIN, RULE_MIN = 0.86, 0.86          # embedding floor; the real filter is lexical overlap below
LABEL_QUERY = {                            # label-specific Russian phrasing added to the retrieval query
    "BRAND_REFERENCE": "указание товарного знака, производителя, модели без слов или эквивалент; описание предмета закупки",
    "NO_EQUIVALENT": "запрет эквивалента, только указанная модель, ограничение конкуренции",
    "EXCESSIVE_PARAMETER": "избыточные требования к характеристикам товара, точные габариты, ограничение количества участников",
    "RESTRICTIVE_QUALIFICATION": "требования к участнику закупки опыт персонал квалификация не предусмотрены положением о закупке",
    "VAGUE_REQUIREMENT": "неконкретное требование, невозможно определить соответствие товара, описание предмета закупки",
    "MISSING_UNIT": "характеристики товара без единиц измерения, значения показателей",
    "CONTRADICTORY_REQUIREMENTS": "противоречивые требования документации к характеристикам товара",
    "INCOMPLETE_STANDARD_REFERENCE": "ссылка на ГОСТ без указания стандарта, требования к товару нормативные документы",
    "MISSING_ACCEPTANCE_CRITERION": "порядок приемки товара, проверка соответствия требованиям документации",
}
STOP = set("это при для или что как его она они оно также либо если того тем чем быть должен должна должны может могут иных иные иной данного данной настоящего".split())
WORD = re.compile(r"[а-яёa-z0-9]{5,}")


def _tokens(text):
    return {w[:6] for w in WORD.findall(text.lower()) if w not in STOP}   # crude stemming: 6-char prefixes


def resolve_evidence(db, ev, rules_idx, prec_idx, clause_text, analysis_type=None, label=None):
    """Turn evidence refs into objects with text; attach precedents / rule parts that are close both semantically
    (embedding) and lexically (shared content-word stems with the clause or the label phrase)."""
    objs = []
    for e in ev:
        if e["type"] == "rule":
            r = db.execute("SELECT rule_id, law, article, part, rule_text FROM legal_rules WHERE rule_id=?", (e["id"],)).fetchone()
            if r: objs.append({"id": r["rule_id"], "type": "rule", "text": f"{r['law']} ст.{r['article']} ч.{r['part'] or ''}: {r['rule_text'][:1200]}"})
        elif e["type"] == "lexicon":
            objs.append({"id": f"lexicon:{e['id']}", "type": "lexicon", "text": f"Внутренний словарь, список «{e['id']}»."})
        elif e["type"] == "clause":
            r = db.execute("SELECT clause_text FROM clauses WHERE clause_id=?", (e["id"],)).fetchone()
            if r: objs.append({"id": e["id"], "type": "clause", "text": r["clause_text"][:600]})
        elif e["type"] == "registry":
            entry = __import__("procdata.checks_doc", fromlist=["registry"]).registry().get(e["id"].replace("ГОСТ Р ", "ГОСТ "), {})
            objs.append({"id": e["id"], "type": "registry", "text": f"Реестр стандартов из корпуса закупок: {e['id']} встречается {entry.get('count', '?')} раз, обычно как «{entry.get('canonical_family', '?')}»."})
        elif e["type"] == "doc":
            objs.append({"id": e["id"], "type": "doc", "text": f"Нормативный или справочный документ: {e['id']}."})
    phrase = LABEL_QUERY.get(label, "")
    query = (phrase + " " + clause_text[:600]).strip()
    ctoks = _tokens(clause_text) | _tokens(phrase)
    want_type = {"COMPETITION": ("TECHNICAL", "QUALIFICATION"), "COMPLETENESS": ("TECHNICAL",)}.get(analysis_type)
    if prec_idx:
        hits = prec_idx.search(query, k=12, filt=lambda r: r["meta"].get("outcome") in ("UPHELD", "DISMISSED")
                               and (not want_type or r["meta"].get("requirement_type") in want_type))
        scored = []
        for p in hits:
            if p["score"] < PREC_MIN: continue
            overlap = len(ctoks & _tokens(p["text"]))
            if overlap >= 4: scored.append((overlap, p))
        for overlap, p in sorted(scored, key=lambda x: (-x[0], -x[1]["score"]))[:2]:
            objs.append({"id": p["id"], "type": "precedent", "score": round(p["score"], 3), "overlap": overlap,
                         "text": f"ФАС, исход {p['meta']['outcome']}, нормы {p['meta'].get('legal_provision')}: {p['text'][:700]}"})
    if rules_idx:
        hits = rules_idx.search(query, k=6, filt=lambda r: r["meta"].get("law") == "223-ФЗ")
        scored = [(len(ctoks & _tokens(r["text"])), r) for r in hits if r["score"] >= RULE_MIN]
        scored = [x for x in scored if x[0] >= 3 and not any(o["id"] == x[1]["id"] for o in objs)]
        for overlap, r in sorted(scored, key=lambda x: (-x[0], -x[1]["score"]))[:1]:
            objs.append({"id": r["id"], "type": "rule", "score": round(r["score"], 3), "overlap": overlap, "text": r["text"][:900]})
    return objs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--procurement", help="ЕИС notice number already in the database")
    ap.add_argument("--category", default=None)
    ap.add_argument("--date", default=None, help="publication date, selects the rule edition (not yet enforced)")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--build-index", action="store_true")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.v else logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(); db = open_db(cfg)
    if a.build_index:
        kb_index.build(db); return
    doc = None
    if a.procurement:
        clauses = clauses_from_db(db, a.procurement); src = f"EIS223:{a.procurement}"
    elif a.path:
        src = str(a.path)
        try:
            path = prepare_file(Path(a.path))
        except UnreadableFile as ex:
            sys.exit(f"cannot review {src}: {ex}")
        try:
            doc = ingest.parse(path); clauses = doc["clauses"]
        except Exception as ex:  # noqa  damaged / unusual file: fall back to flat text extraction
            log.warning("structured ingest failed (%s); falling back to flat text", ex)
            try:
                clauses = clauses_from_file(path)
            except Exception as ex2:  # noqa
                sys.exit(f"cannot review {src}: файл поврежден или не читается ({type(ex2).__name__})")
        if not clauses:
            sys.exit(f"cannot review {src}: текст не извлечен (пустой документ или скан без текстового слоя)")
    else:
        ap.error("give a file path or --procurement")
    log.info("%s: %d clauses", src, len(clauses))
    findings = analyze(clauses, doc)
    try:
        rules_idx, prec_idx = kb_index.Index("rules"), kb_index.Index("precedents")
    except Exception as ex:  # noqa
        log.warning("retrieval index unavailable (%s); run --build-index", ex); rules_idx = prec_idx = None
    use_llm = not a.no_llm and explain.available()
    if not a.no_llm and not explain.available():
        log.warning("LLM model file missing (models/qwen2.5-7b-instruct-q4_k_m.gguf); explanations stay rule-based")
    for f in findings:
        objs = resolve_evidence(db, f["evidence"], rules_idx, prec_idx, f["clause_text"], f["analysis_type"], f["label"])
        f["evidence_objects"] = objs
        if use_llm and explain.wants_llm(f):
            explain.explain(f, objs)
    kb_release = {"db": cfg["db_path"], "snapshot_date": str(datetime.date.today()),
                  "legal_rules": db.execute("SELECT COUNT(*) FROM legal_rules").fetchone()[0],
                  "fas_findings": db.execute("SELECT COUNT(*) FROM fas_findings").fetchone()[0]}
    by_type = {}
    for f in findings: by_type.setdefault(f["analysis_type"], []).append(f)
    scopes = {}
    for c in clauses: scopes[c.get("scope", "?")] = scopes.get(c.get("scope", "?"), 0) + 1
    report = {"source": src, "clause_scopes": scopes, "conclusion": conclusion(findings, doc), "reviewed_at": datetime.datetime.now().isoformat(timespec="seconds"), "kb_release": kb_release,
              "n_clauses": len(clauses), "summary": {k: {"findings": len(v), "errors": sum(x["severity"] == "ERROR" for x in v),
                                                          "risks": sum(x["severity"] == "RISK" for x in v)} for k, v in by_type.items()},
              "findings": findings}
    out = Path(a.out) if a.out else ROOT / "data" / "reviews" / (re.sub(r"\W", "_", src) + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    report["document_view"] = rep.document_view(doc, clauses)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".html").write_text(rep.render_html(report), encoding="utf-8")
    try: rep.render_docx(report, out.with_suffix(".docx"))
    except Exception as ex:  # noqa
        log.warning("docx report failed: %s", ex)
    con = report["conclusion"]
    md = [f"# Review: {src}", f"clauses: {len(clauses)}", "", f"## Заключение: {con['verdict']}",
          f"ошибок: {con['errors']} · рисков: {con['risks']} · на ручную проверку: {con['manual_review']} · по категориям: {con['by_category']}", ""]
    for k in ("COMPLETENESS", "COMPETITION", "COMPLIANCE"):
        fs = by_type.get(k, [])
        md.append(f"## {k}: {len(fs)} findings")
        for f in fs[:60]:
            where = (f.get("anchors") or [None])[0] or (f"стр. {f.get('page')}" if f.get("page") else f.get("clause_id"))
            md.append(f"- **{f['label']}** [{f.get('case_category')}, {f['severity']}, {f['disposition']}] {f['explanation']}")
            md.append(f"  - где: {where}")
            md.append(f"  - фрагмент: «{f['clause_text'][:200]}»")
            if f.get("proposed_text"): md.append(f"  - предложение: {f['proposed_text']}")
            cites = [o['id'] for o in f["evidence_objects"]]
            if cites: md.append(f"  - доказательства: {', '.join(cites)}")
        md.append("")
    out.with_suffix(".md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False)); print("report:", out, "and", out.with_suffix(".md"))


if __name__ == "__main__":
    main()
