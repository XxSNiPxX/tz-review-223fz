"""Statute texts (223-ФЗ, 44-ФЗ) from several sources; keep every copy, merge into legal_rules.

Sources, in priority order for the merged legal_rules table:
  consultant  - www.consultant.ru TOC page -> one HTML page per article (verified live; clean part numbering)
  garant      - base.garant.ru/<id>/ -> per-article pages (windows-1251)
  pravo       - pravo.gov.ru ИПС; the frameset loads ?doc_itself=&nd=<nd>&page=N (windows-1251, paginated).
                nd for 223-ФЗ must be set in config (the one shipped earlier was a different act).
  ruslawod    - RusLawOD corpus on Hugging Face (irlspbru/RusLawOD, parquet, scraped from pravo.gov.ru,
                CC BY-NC(-SA) 4.0). Streams the 6 GB corpus and keeps the law + every amending act.
  docx_urls   - any direct .docx/.pdf links you put in config (e.g. a ministry's copy of the law).
Each successful fetch is stored in documents + law_texts. legal_rules rows are per article and part;
later sources only fill rule_ids that earlier sources did not produce (INSERT OR IGNORE).
"""
import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .common import log, http_session, polite_get, upsert, sha256_file

ART_HEAD = re.compile(r"(?m)^\s*Статья\s+(\d+(?:[.\-]\d+)*)\.?\s*(.*)$")
PART = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)\.\s+(?=\S)")
NOISE = re.compile(r"(Путеводитель по спорам.*?)(?=\n\s*1\.\s)", re.S)


def _store_text(db, cfg, law, source, url, text, out_dir, raw=None, fmt="TXT", note=None):
    law_dir = out_dir / "legal"; law_dir.mkdir(parents=True, exist_ok=True)
    path = law_dir / f"{law}.{source}.{fmt.lower()}"
    path.write_bytes(raw) if raw else path.write_text(text, encoding="utf-8")
    (law_dir / f"{law}.{source}.txt").write_text(text, encoding="utf-8")
    doc_id = f"LAW:{law}:{source}"
    upsert(db, "documents", {"document_id": doc_id, "document_type": "law", "source_url": url,
                             "original_filename": f"{law} ({source})", "storage_path": str(path),
                             "file_hash": sha256_file(path), "file_format": fmt, "extraction_status": "extracted"},
           "document_id")
    return doc_id


def _rules_from_text(db, law, source, doc_id, text):
    """Split a whole-law text into articles and parts -> legal_rules (INSERT OR IGNORE)."""
    heads = list(ART_HEAD.finditer(text))
    n = 0
    for i, m in enumerate(heads):
        body = text[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)].strip()
        n += _rules_from_article(db, law, source, doc_id, m.group(1), m.group(2).strip(), body)
    return n


def _rules_from_article(db, law, source, doc_id, art, title, body):
    tag = law.replace("-", "")
    body = NOISE.sub("", body)
    db.execute("INSERT OR IGNORE INTO legal_rules(rule_id, source_document_id, law, article, rule_title, rule_text, "
               "rule_category, source) VALUES (?,?,?,?,?,?,?,?)",
               (f"{tag}_ART{art}", doc_id, law, art, title, body, "statute_article", source))
    parts = list(PART.finditer(body))
    for j, pm in enumerate(parts):
        ptext = body[pm.start(): parts[j + 1].start() if j + 1 < len(parts) else len(body)].strip()
        db.execute("INSERT OR IGNORE INTO legal_rules(rule_id, source_document_id, law, article, part, rule_title, "
                   "rule_text, rule_category, source) VALUES (?,?,?,?,?,?,?,?,?)",
                   (f"{tag}_ART{art}_P{pm.group(1)}", doc_id, law, art, pm.group(1), title, ptext, "statute_part", source))
    return 1


def _clean_html_text(html, main_selectors=()):
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "nav", "footer", "header", "noscript"]): t.decompose()
    node = None
    for sel in main_selectors:
        node = soup.select_one(sel)
        if node: break
    text = (node or soup).get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def _decode(r):
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "windows-1251"
    return r.text


# ---------------------------------------------------------------- consultant.ru
def src_consultant(db, cfg, law, spec, s, out_dir):
    base = f"https://www.consultant.ru/document/cons_doc_LAW_{spec['consultant_id']}/"
    r = polite_get(s, base, delay=1.5)
    if r is None: return 0
    soup = BeautifulSoup(r.text, "lxml")
    links = []
    for a in soup.select(f'a[href*="cons_doc_LAW_{spec["consultant_id"]}/"]'):
        href = a.get("href", "")
        if re.search(r"/[0-9a-f]{40}/?$", href) and href not in [l for l, _ in links]:
            links.append((href, a.get_text(" ", strip=True)))
    edition = soup.find(string=re.compile(r"ред\. от|от \d{2}\.\d{2}\.\d{4} N \d+-ФЗ"))
    doc_id = None
    full = []
    n = 0
    for href, label in links:
        m = ART_HEAD.match(label) or re.match(r"Статья\s+(\d+(?:[.\-]\d+)*)\.?\s*(.*)", label)
        if not m: continue
        rr = polite_get(s, urljoin(base, href), delay=1.5)
        if rr is None: continue
        text = _clean_html_text(rr.text, (".document-page__content", ".text", "#content", "main"))
        # Keep only from the article heading onwards
        k = text.find(f"Статья {m.group(1)}")
        if k >= 0: text = text[k:]
        text = re.split(r"\nОткрыть полный текст документа", text)[0]
        full.append(text)
        if doc_id is None:
            doc_id = _store_text(db, cfg, law, "consultant", base, "", out_dir, fmt="TXT", note=str(edition))
        body = text.split("\n", 1)[1] if "\n" in text else ""
        n += _rules_from_article(db, law, "consultant", doc_id, m.group(1), m.group(2).strip(), body)
    if full:
        _store_text(db, cfg, law, "consultant", base, "\n\n".join(full), out_dir, note=str(edition))
        upsert(db, "law_texts", {"law": law, "source": "consultant", "source_url": base, "n_articles": n,
                                 "edition_note": str(edition)[:200] if edition else None,
                                 "storage_path": str(out_dir / "legal" / f"{law}.consultant.txt")}, "law, source")
    return n


# ---------------------------------------------------------------- garant.ru
def src_garant(db, cfg, law, spec, s, out_dir):
    base = f"https://base.garant.ru/{spec['garant_id']}/"
    r = polite_get(s, base, delay=1.5)
    if r is None: return 0
    html = _decode(r)
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select(f'a[href*="/{spec["garant_id"]}/"]'):
        href = a.get("href", "")
        if re.search(r"/[0-9a-f]{32}/?$", href) and ART_HEAD.match(a.get_text(" ", strip=True) or ""):
            links.append((href, a.get_text(" ", strip=True)))
    full, n, doc_id = [], 0, None
    for href, label in dict.fromkeys(links):
        rr = polite_get(s, urljoin(base, href), delay=1.5)
        if rr is None: continue
        text = _clean_html_text(_decode(rr), ("#text", ".text", "main"))
        m = ART_HEAD.match(label)
        k = text.find(f"Статья {m.group(1)}")
        if k >= 0: text = text[k:]
        full.append(text)
        if doc_id is None:
            doc_id = _store_text(db, cfg, law, "garant", base, "", out_dir)
        body = text.split("\n", 1)[1] if "\n" in text else ""
        n += _rules_from_article(db, law, "garant", doc_id, m.group(1), m.group(2).strip(), body)
    if full:
        _store_text(db, cfg, law, "garant", base, "\n\n".join(full), out_dir)
        upsert(db, "law_texts", {"law": law, "source": "garant", "source_url": base, "n_articles": n,
                                 "storage_path": str(out_dir / "legal" / f"{law}.garant.txt")}, "law, source")
    return n


# ---------------------------------------------------------------- pravo.gov.ru
def src_pravo(db, cfg, law, spec, s, out_dir):
    nd = spec.get("pravo_nd")
    if not nd:
        log.warning("%s: no pravo_nd in config; skip pravo.gov.ru (fill it from RusLawOD pravogovruNd)", law); return 0
    # The frame pages answer 204 without the session cookie set by the outer document page.
    polite_get(s, f"http://pravo.gov.ru/proxy/ips/?docbody=&nd={nd}", delay=1.0, timeout=40,
               headers={"Referer": "http://pravo.gov.ru/proxy/ips/"})
    pages, page = [], 1
    while page <= 400:
        url = f"http://pravo.gov.ru/proxy/ips/?doc_itself=&nd={nd}&page={page}&rdk={spec.get('pravo_rdk', 0)}"
        r = polite_get(s, url, delay=1.0, timeout=40, headers={"Referer": f"http://pravo.gov.ru/proxy/ips/?docbody=&nd={nd}"})
        if r is None: break
        r.encoding = "windows-1251"
        text = _clean_html_text(r.text)
        if len(text) < 200 or (pages and text == pages[-1]):
            break
        pages.append(text); page += 1
    if not pages: return 0
    text = "\n".join(pages)
    doc_id = _store_text(db, cfg, law, "pravo", f"http://pravo.gov.ru/proxy/ips/?docbody=&nd={nd}", text, out_dir)
    n = _rules_from_text(db, law, "pravo", doc_id, text)
    upsert(db, "law_texts", {"law": law, "source": "pravo", "source_url": f"nd={nd}", "n_articles": n,
                             "storage_path": str(out_dir / "legal" / f"{law}.pravo.txt")}, "law, source")
    return n


# ---------------------------------------------------------------- RusLawOD (Hugging Face)
def src_ruslawod(db, cfg, laws, out_dir):
    """Read the corpus parquet files remotely with column projection + predicate pushdown, so only the
    metadata columns and the matching rows' text are transferred. pip install pyarrow huggingface_hub.
    Match = exact (number, signing date) for the law itself, or an amending act whose heading names the law."""
    try:
        import pyarrow.dataset as pds, pyarrow.compute as pc
        from huggingface_hub import HfFileSystem
    except ImportError:
        log.warning("pyarrow/huggingface_hub not installed; skip RusLawOD"); return 0
    fs = HfFileSystem()
    files = sorted(f for f in fs.ls("datasets/irlspbru/RusLawOD", detail=False) if f.endswith(".parquet"))
    ds = pds.dataset(files, filesystem=fs, format="parquet")
    expr = None
    for law, spec in laws.items():
        e = (pc.field("docNumberIPS") == spec["number"]) & (pc.field("docdateIPS") == spec["signing_date"])
        if spec.get("title_substring"):
            e = e | pc.match_substring(pc.field("headingIPS"), spec["title_substring"])
        expr = e if expr is None else (expr | e)
    cols = ["pravogovruNd", "docNumberIPS", "docdateIPS", "headingIPS", "statusIPS", "actual_datetime_humanIPS", "textIPS"]
    found = 0
    for batch in ds.to_batches(columns=cols, filter=expr, batch_size=64):
        for row in batch.to_pylist():
            num, date, head = (row.get("docNumberIPS") or "").strip(), row.get("docdateIPS") or "", row.get("headingIPS") or ""
            law = next((l for l, sp in laws.items() if num == sp["number"] and date == sp["signing_date"]), None)
            if law is None:
                law = next((l for l, sp in laws.items() if sp.get("title_substring") and sp["title_substring"] in head), None)
                # amendments only: real federal laws, not bills, Duma resolutions or letters about them
                if law is None or "внесении изменени" not in head.lower() or not num.endswith("ФЗ") \
                        or head.startswith(("О проекте", "О Федеральном законе", "О внесении в Государственную Думу")):
                    continue
                kind = "amendment"
            else:
                kind = "law"
            nd = row.get("pravogovruNd")
            safe_num = re.sub(r"\W", "", num)
            source = "ruslawod" if kind == "law" else f"ruslawod_amend_{date.replace('.', '')}_{safe_num}"
            text = row.get("textIPS") or ""
            doc_id = _store_text(db, cfg, law, source, f"https://huggingface.co/datasets/irlspbru/RusLawOD (nd={nd})",
                                 text, out_dir, note=head[:200])
            db.execute("UPDATE documents SET document_type=?, publication_date=?, description=? WHERE document_id=?",
                       (kind, date, head[:500], doc_id))
            n = _rules_from_text(db, law, source, doc_id, text) if kind == "law" else 0
            upsert(db, "law_texts", {"law": law, "source": source, "source_url": f"pravogovruNd={nd}", "n_articles": n,
                                     "edition_note": f"{head[:150]} | status={row.get('statusIPS')} | scraped={row.get('actual_datetime_humanIPS')}",
                                     "storage_path": str(out_dir / "legal" / f"{law}.{source}.txt")}, "law, source")
            if kind == "law" and nd:
                log.info("%s: pravo.gov.ru nd=%s (put as pravo_nd in config.yaml)", law, nd)
            found += 1
        db.commit()
    log.info("RusLawOD: %d matching acts (law + amendments)", found)
    return found


# ---------------------------------------------------------------- direct files
def src_files(db, cfg, law, spec, s, out_dir):
    n = 0
    for url in spec.get("file_urls", []):
        r = polite_get(s, url, delay=1.0)
        if r is None: continue
        ext = Path(url.split("?")[0]).suffix.lower()
        tmp = out_dir / "legal" / f"{law}.file{n}{ext}"; tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(r.content)
        try:
            if ext == ".docx":
                from .extract_text import _docx; text = _docx(tmp)[0][1]
            elif ext == ".pdf":
                from .extract_text import _pdf; text = "\n".join(t for _, t in _pdf(tmp))
            else:
                text = _clean_html_text(_decode(r))
        except Exception as ex:  # noqa
            log.error("cannot read %s: %s", url, ex); continue
        doc_id = _store_text(db, cfg, law, f"file{n}", url, text, out_dir, raw=r.content, fmt=ext.lstrip(".").upper() or "BIN")
        k = _rules_from_text(db, law, f"file{n}", doc_id, text)
        upsert(db, "law_texts", {"law": law, "source": f"file{n}", "source_url": url, "n_articles": k,
                                 "storage_path": str(tmp)}, "law, source")
        n += 1
    return n


SOURCES = {"consultant": src_consultant, "garant": src_garant, "pravo": src_pravo, "files": src_files}


def collect(db, cfg, out_dir: Path):
    lc = cfg["legal"]
    s = http_session()
    for law, spec in lc["laws"].items():
        for name in lc.get("sources", ["consultant", "garant", "pravo", "files"]):
            if name == "ruslawod": continue
            try:
                n = SOURCES[name](db, cfg, law, spec, s, out_dir)
                log.info("%s / %s: %s articles", law, name, n)
            except Exception as ex:  # noqa
                log.error("%s / %s failed: %s", law, name, ex)
            db.commit()
    if "ruslawod" in lc.get("sources", []):
        src_ruslawod(db, cfg, lc["laws"], out_dir)
    for r in db.execute("SELECT law, source, n_articles FROM law_texts ORDER BY law, source"):
        log.info("have %s from %s (%s articles)", r[0], r[1], r[2])
