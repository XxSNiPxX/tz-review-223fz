"""FAS decisions from br.fas.gov.ru (verified against the live site, Nov 2026).

Two entry points on the site:
  * cases:      https://br.fas.gov.ru/?type=0&procedure=43021&page=N  (procedure 43021 = "223-ФЗ – жалоба")
                case page /cases/<uuid>/ : procedure, dates, office, stage, participants, linked documents (/to/...)
  * documents:  https://br.fas.gov.ru/?type=1&text=<query>&page=N  -> /to/<office-slug>/<uuid>/
                document page: "Вид документа", "Дата регистрации", "Управление", "Дело", "Текст документа"
Both pages are plain label/value lists, parsed from text lines. Heuristic fields (outcome, cited articles,
notice number) are pre-labels for annotators.
"""
import json, re
from pathlib import Path
from urllib.parse import urljoin, urlencode
from bs4 import BeautifulSoup
from .common import log, http_session, polite_get, upsert, sha256_file

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
CASE_LINK = re.compile(rf"/cases/({UUID})/")
DOC_LINK = re.compile(rf"/to/([a-z0-9\-]+)/({UUID})/")
NOTICE_NUM = re.compile(r"(?:извещени[ея]|закупк[аи]|№)\s*№?\s*(3\d{10})\b", re.I)
ANY_223_NUM = re.compile(r"\b(3\d{10})\b")
ARTICLE = re.compile(r"(?:п(?:ункт[аеу]?|\.)\s*([\d.]+)\s+)?(?:ч(?:аст[иь]|\.)\s*([\d.]+)\s+)?ст(?:ать[иея]й?|\.)\s*([\d.]+)"
                     r"\s*(?:Федерального\s+)?(?:закона\s*)?(?:от\s+[\d.]+\s*)?(?:№\s*)?(223|44|135)-ФЗ", re.I)
CASE_LABELS = ["Процедура", "Дата регистрации", "Управление", "Сфера деятельности", "Дата возбуждения",
               "Стадия рассмотрения", "Дата закрытия", "Участники дела", "Связанные документы и дела"]
DOC_LABELS = ["Вид документа", "Дата регистрации", "Управление", "Сфера деятельности", "Дело", "Процедура",
              "Приложения", "Текст документа"]


def _lines(html):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "footer", "noscript"]):
        t.decompose()
    text = soup.get_text("\n")
    return [l.strip() for l in text.split("\n") if l.strip()], soup


def _label_values(lines, labels):
    """Pair each known label with the text up to the next known label."""
    out, i = {}, 0
    idx = [k for k, l in enumerate(lines) if l in labels]
    for a, b in zip(idx, idx[1:] + [len(lines)]):
        out[lines[a]] = "\n".join(lines[a + 1:b]).strip()
    return out


def outcome(text):
    """Heuristic disposition from the operative part (after РЕШИЛА). Party names between 'жалобу' and the verdict
    can be several hundred characters long, and the verb order varies ('признать жалобу X необоснованной' vs
    'Жалобу X признать необоснованной')."""
    t = re.sub(r"\s+", " ", text)
    o = t.lower()
    # "не обоснованной" / "не-\nобоснованной" are frequent in scanned decisions: glue the negation
    o = re.sub(r"\bне\s*-?\s*(обоснованн)", r"не\1", o)
    k = o.rfind("решила")
    o = o[k:] if k >= 0 else o
    if re.search(r"жалоб\w*.{0,700}?(частично обоснованн|обоснованн\w+ в части)", o): return "PARTIALLY_UPHELD"
    if re.search(r"жалоб\w*.{0,700}?необоснованн|необоснованн\w+.{0,60}?жалоб", o): return "DISMISSED"
    if re.search(r"жалоб\w*.{0,700}?(?<!не)обоснованн|(?<!не)обоснованн\w+.{0,60}?жалоб", o): return "UPHELD"
    if re.search(r"прекратить рассмотрение|прекратить|без рассмотрения|отозва|отзыв|возвратить жалобу|отказать в рассмотрении", o):
        return "NOT_CONSIDERED"
    return "UNKNOWN"


def cited_articles(text):
    out = set()
    for point, part, art, law in ARTICLE.findall(text):
        s = f"{law}-ФЗ ст.{art}"
        if part: s += f" ч.{part}"
        if point: s += f" п.{point}"
        out.add(s)
    return sorted(out)


def _law_type(text, procedure=""):
    if "223-ФЗ" in procedure or "223-фз" in text.lower(): return "223-FZ"
    if "44-ФЗ" in procedure or "44-фз" in text.lower(): return "44-FZ"
    return "unknown"


def collect(db, cfg, out_dir: Path):
    f = cfg["fas"]
    s = http_session()
    html_dir = out_dir / "fas" / "html"; html_dir.mkdir(parents=True, exist_ok=True)
    base = f["base_url"].rstrip("/")
    n_cases = n_docs = 0
    # 1) case listing filtered to 223-ФЗ complaints
    if f.get("crawl_cases", True):
        params = {"type": 0, "procedure": f.get("procedure_id", 43021)}
        if f.get("date_from"): params["start_date"] = f["date_from"]      # dd.mm.yyyy
        if f.get("date_to"): params["finish_date"] = f["date_to"]
        for page in range(f.get("cases_page_from", 1), f.get("cases_page_to", 5) + 1):
            r = polite_get(s, f"{base}/?{urlencode({**params, 'page': page})}", delay=f["delay_sec"])
            if r is None: break
            ids = list(dict.fromkeys(CASE_LINK.findall(r.text)))
            if not ids: log.info("no cases on page %d, stopping", page); break
            for cid in ids:
                n_cases += _fetch_case(db, s, f, base, cid, html_dir)
            db.commit()
    # 2) full-text document search
    for q in f.get("queries", []):
        for page in range(1, f["max_pages_per_query"] + 1):
            r = polite_get(s, f"{base}/?{urlencode({'type': 1, 'text': q, 'page': page})}", delay=f["delay_sec"])
            if r is None: break
            docs = list(dict.fromkeys(DOC_LINK.findall(r.text)))
            if not docs: break
            for office, did in docs:
                n_docs += _fetch_document(db, s, f, base, office, did, html_dir, case_id=None)
            db.commit()
    log.info("FAS: %d cases, %d documents fetched", n_cases, n_docs)


def _fetch_case(db, s, f, base, cid, html_dir):
    if db.execute("SELECT 1 FROM fas_cases WHERE case_id=? AND title IS NOT NULL", (cid,)).fetchone():
        return 0
    url = f"{base}/cases/{cid}/"
    r = polite_get(s, url, delay=f["delay_sec"])
    if r is None: return 0
    (html_dir / f"case_{cid}.html").write_text(r.text, encoding="utf-8")
    lines, soup = _lines(r.text)
    title = next((l for l in lines if l.startswith("Дело №")), "")
    lv = _label_values(lines, CASE_LABELS)
    participants = []
    plines = lv.get("Участники дела", "").split("\n")
    for i, l in enumerate(plines):
        m = re.search(r"ИНН\s*(\d+)", l)
        if m and i > 0:
            role = plines[i + 1] if i + 1 < len(plines) else ""
            participants.append({"name": plines[i - 1], "inn": m.group(1), "role": role})
    m = re.search(r"Дело №([^\s]+)", title)
    row = {"case_id": cid, "title": title[:300], "case_number": m.group(1) if m else None,
           "procedure": lv.get("Процедура"), "fas_office": lv.get("Управление"),
           "decision_date": lv.get("Дата регистрации"), "stage": lv.get("Стадия рассмотрения"),
           "participants": json.dumps(participants, ensure_ascii=False),
           "law_type": _law_type("", lv.get("Процедура", "")), "source_url": url}
    upsert(db, "fas_cases", row, "case_id")
    n = 1
    for office, did in dict.fromkeys(DOC_LINK.findall(r.text)):
        n += _fetch_document(db, s, f, base, office, did, html_dir, case_id=cid)
    return n


def _fetch_document(db, s, f, base, office, did, html_dir, case_id):
    doc_id = f"FAS:{did}"
    if db.execute("SELECT 1 FROM documents WHERE document_id=?", (doc_id,)).fetchone():
        if case_id: db.execute("UPDATE fas_documents SET case_id=COALESCE(case_id,?) WHERE doc_uuid=?", (case_id, did))
        return 0
    url = f"{base}/to/{office}/{did}/"
    r = polite_get(s, url, delay=f["delay_sec"])
    if r is None: return 0
    path = html_dir / f"doc_{did}.html"; path.write_text(r.text, encoding="utf-8")
    lines, soup = _lines(r.text)
    lv = _label_values(lines, DOC_LABELS)
    text = lv.get("Текст документа", "").replace("Сохранить как PDF", "").strip()
    title = next((l for l in lines if re.search(r"(РЕШЕНИЕ|ПРЕДПИСАНИЕ|Телеграмма|Уведомление|Определение)", l)), "")[:300]
    notice = NOTICE_NUM.search(text) or ANY_223_NUM.search(text)
    eis = notice.group(1) if notice else None
    kind = lv.get("Вид документа", "")
    oc = outcome(text) if ("РЕШЕНИЕ" in title.upper() or "решени" in kind.lower() or "РЕШИЛА" in text) else "N/A"
    # ensure case row exists if we learned the case here
    case_m = re.search(rf"/cases/({UUID})/", r.text)
    cid = case_id or (case_m.group(1) if case_m else None)
    if cid:
        db.execute("INSERT OR IGNORE INTO fas_cases(case_id, source_url) VALUES (?,?)", (cid, f"{base}/cases/{cid}/"))
    upsert(db, "documents", {"document_id": doc_id, "procurement_id": f"EIS223:{eis}" if eis else None,
                             "document_type": "fas_decision", "original_filename": title, "source_url": url,
                             "storage_path": str(path), "file_hash": sha256_file(path), "file_format": "HTML",
                             "publication_date": lv.get("Дата регистрации"), "extraction_status": "extracted"}, "document_id")
    upsert(db, "fas_documents", {
        "doc_uuid": did, "document_id": doc_id, "case_id": cid, "doc_kind": kind, "title": title,
        "fas_office": lv.get("Управление") or office, "doc_date": lv.get("Дата регистрации"),
        "procedure": lv.get("Процедура"), "eis_id_mentioned": eis,
        "procurement_id": f"EIS223:{eis}" if eis else None, "law_type": _law_type(text, lv.get("Процедура", "")),
        "outcome": oc, "legal_basis": json.dumps(cited_articles(text), ensure_ascii=False),
        "source_url": url, "full_text": text}, "doc_uuid")
    if cid and oc not in ("N/A", "UNKNOWN"):
        db.execute("UPDATE fas_cases SET outcome=?, violation_established=?, decision_document_id=?, "
                   "procurement_id=COALESCE(procurement_id,?), eis_id_mentioned=COALESCE(eis_id_mentioned,?), "
                   "legal_basis=? WHERE case_id=?",
                   (oc, {"UPHELD": "yes", "PARTIALLY_UPHELD": "yes", "DISMISSED": "no"}.get(oc, "unclear"), doc_id,
                    f"EIS223:{eis}" if eis else None, eis, json.dumps(cited_articles(text), ensure_ascii=False), cid))
    return 1


def relabel(db):
    """Recompute heuristic fields for already stored documents (after improving the regexes)."""
    rows = db.execute("SELECT doc_uuid, case_id, document_id, title, doc_kind, full_text FROM fas_documents").fetchall()
    for r in rows:
        text = r["full_text"] or ""
        is_decision = "РЕШЕНИЕ" in (r["title"] or "").upper() or "решени" in (r["doc_kind"] or "").lower() or "РЕШИЛА" in text
        oc = outcome(text) if is_decision else "N/A"
        notice = NOTICE_NUM.search(text) or ANY_223_NUM.search(text)
        eis = notice.group(1) if notice else None
        basis = json.dumps(cited_articles(text), ensure_ascii=False)
        db.execute("UPDATE fas_documents SET outcome=?, legal_basis=?, eis_id_mentioned=?, procurement_id=? WHERE doc_uuid=?",
                   (oc, basis, eis, f"EIS223:{eis}" if eis else None, r["doc_uuid"]))
        if r["case_id"] and oc not in ("N/A", "UNKNOWN"):
            db.execute("UPDATE fas_cases SET outcome=?, violation_established=?, decision_document_id=?, legal_basis=?, "
                       "procurement_id=COALESCE(procurement_id,?), eis_id_mentioned=COALESCE(eis_id_mentioned,?) WHERE case_id=?",
                       (oc, {"UPHELD": "yes", "PARTIALLY_UPHELD": "yes", "DISMISSED": "no"}.get(oc, "unclear"),
                        r["document_id"], basis, f"EIS223:{eis}" if eis else None, eis, r["case_id"]))
    db.commit()
    log.info("relabelled %d FAS documents", len(rows))
