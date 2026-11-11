"""Fallback for ЕИС when the FTP is unavailable: the public HTML search of zakupki.gov.ru.

UNVERIFIED against the live site (it refuses foreign traffic and the browser pane here). URL patterns are the
long-standing public ones; adjust selectors from a saved page in data/eis_html/ if counts look wrong.
Requires a Russian IP. Keep delays high; the site rate-limits aggressively.

  search:   /epz/order/extendedsearch/results.html?fz223=on&searchString=..&pageNumber=N&recordsPerPage=_50
  notice:   /223/purchase/public/purchase/info/common-info.html?regNumber=<11 digits>
  files:    /223/purchase/public/purchase/info/documents.html?regNumber=<11 digits>
  attachment links: /223/purchase/public/download/download.html?id=<n>
Also useful (not automated): complaints registry /epz/complaint/search/results.html?fz223=on
"""
import re, time
from pathlib import Path
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from .common import log, http_session, polite_get, upsert

BASE = "https://zakupki.gov.ru"
REG = re.compile(r"regNumber=(3\d{10})")
DL = re.compile(r"/223/purchase/public/download/download\.html\?id=\d+")


def _kv(soup):
    """New (2024+) card layout: <div class=common-text__title>label</div><div class=common-text__value>value</div>."""
    out = {}
    for t in soup.select(".common-text__title, .section__title"):
        v = t.find_next_sibling(class_=["common-text__value", "section__info"])
        if v:
            out[t.get_text(" ", strip=True)] = re.sub(r"\s+", " ", v.get_text(" ", strip=True))
    return out


def collect(db, cfg, out_dir: Path):
    e = cfg["eis"]
    h = e.get("html", {})
    s = http_session(e["http_user_agent"])
    save = out_dir / "eis_html"; save.mkdir(parents=True, exist_ok=True)
    regs = []
    for q in h.get("search_strings", [""]):
        for page in range(1, h.get("max_pages", 3) + 1):
            params = {"fz223": "on", "searchString": q, "pageNumber": page, "recordsPerPage": "_50",
                      "sortBy": "UPDATE_DATE", "af": "on"}
            if h.get("publish_from"): params["publishDateFrom"] = h["publish_from"]   # dd.mm.yyyy
            if h.get("publish_to"): params["publishDateTo"] = h["publish_to"]
            r = polite_get(s, f"{BASE}/epz/order/extendedsearch/results.html?{urlencode(params)}", delay=h.get("delay_sec", 4))
            if r is None: break
            safe_q = re.sub(r"\W", "_", q)
            (save / f"search_{safe_q}_{page}.html").write_text(r.text, encoding="utf-8")
            found = list(dict.fromkeys(REG.findall(r.text)))
            if not found:
                log.warning("no regNumbers on page %d for %r (blocked? see saved html)", page, q); break
            regs += found
    regs = list(dict.fromkeys(regs))
    log.info("EIS html: %d notices found", len(regs))
    for reg in regs:
        _fetch_notice(db, s, h, reg, save)
        db.commit()


def _fetch_notice(db, s, h, reg, save):
    pid = f"EIS223:{reg}"
    url = f"{BASE}/epz/order/notice/notice223/common-info.html?regNumber={reg}"
    r = polite_get(s, url, delay=h.get("delay_sec", 4))
    if r is None: return
    (save / f"notice_{reg}.html").write_text(r.text, encoding="utf-8")
    soup = BeautifulSoup(r.text, "lxml")
    kv = _kv(soup)
    text = re.sub(r"\s+", " ", soup.get_text(" "))
    def pick(*keys):
        for k in keys:
            for kk, v in kv.items():
                if k.lower() in kk.lower(): return v
        return None
    price_m = re.search(r"Начальная[^₽]{0,60}?цена\s*([\d\s]+(?:[.,]\d+)?)\s*₽", text)
    inn_m = re.search(r"ИНН\s*(\d{10,12})", text)
    guid_m = re.search(r"noticeGuid=([0-9a-f\-]{36})", r.text)
    okpd_m = re.search(r"ОКПД2[^\d]{0,40}(\d{2}(?:\.\d{1,3}){0,4})", text)
    upsert(db, "procurements", {
        "procurement_id": pid, "eis_id": reg, "law_type": "223-FZ",
        "name": pick("Наименование закупки", "Наименование предмета"),
        "customer_name": pick("Наименование организации", "Заказчик"), "customer_id": inn_m.group(1) if inn_m else None,
        "procurement_method": pick("Способ осуществления закупки", "Способ закупки"),
        "publication_date": pick("Дата размещения извещения", "Дата размещения"),
        "submission_deadline": pick("Дата и время окончания срока подачи заявок", "окончания подачи"),
        "procurement_status": pick("Этап закупки", "Статус"), "okpd2_code": okpd_m.group(1) if okpd_m else None,
        "initial_price": float(price_m.group(1).replace(" ", "").replace(",", ".")) if price_m else None, "currency": "RUB" if price_m else None,
        "source_url": url, "source_archive": "html", "raw_xml_path": str(save / f"notice_{reg}.html")}, "procurement_id")
    if not guid_m:
        log.warning("%s: noticeGuid not found, cannot open documents tab", reg); return
    durl = f"{BASE}/epz/order/notice/notice223/documents.html?purchaseNoticeNumber={reg}&noticeGuid={guid_m.group(1)}"
    r2 = polite_get(s, durl, delay=h.get("delay_sec", 4))
    if r2 is None: return
    (save / f"documents_{reg}.html").write_text(r2.text, encoding="utf-8")
    soup = BeautifulSoup(r2.text, "lxml")
    n = 0
    for a in soup.select("a[href*='filestore/public/1.0/download']"):
        href = a.get("href"); name = a.get_text(" ", strip=True) or "file"
        uid = re.search(r"uid=([0-9A-Fa-f]+)", href)
        if not uid: continue
        url_f = href if href.startswith("http") else BASE + href
        upsert(db, "documents", {"document_id": f"{pid}:att:{uid.group(1)}", "procurement_id": pid,
                                 "document_type": "attachment", "original_filename": name, "source_url": url_f,
                                 "file_format": (Path(name).suffix.lstrip(".").upper() or None),
                                 "extraction_status": "pending"}, "document_id")
        n += 1
    log.info("%s: %s | %d attachment links", reg, (pick("Наименование закупки") or "")[:60], n)


def collect_linked(db, cfg, out_dir: Path, limit=None):
    """Fetch exactly the notices that FAS decisions mention (fas_cases / fas_documents), newest first."""
    e = cfg["eis"]; h = e.get("html", {})
    s = http_session(e["http_user_agent"])
    save = out_dir / "eis_html"; save.mkdir(parents=True, exist_ok=True)
    regs = [r[0] for r in db.execute(
        "SELECT eis_id_mentioned FROM fas_documents WHERE eis_id_mentioned IS NOT NULL "
        "UNION SELECT eis_id_mentioned FROM fas_cases WHERE eis_id_mentioned IS NOT NULL ORDER BY 1 DESC")]
    done = {r[0] for r in db.execute("SELECT eis_id FROM procurements WHERE name IS NOT NULL")}
    todo = [r for r in regs if r not in done][: int(limit) if limit else None]
    log.info("EIS linked: %d notices referenced by FAS, %d already fetched, %d to do now", len(regs), len(done), len(todo))
    ok = 0
    for i, reg in enumerate(todo, 1):
        try:
            _fetch_notice(db, s, h, reg, save)
            ok += db.execute("SELECT name IS NOT NULL FROM procurements WHERE eis_id=?", (reg,)).fetchone()[0] or 0
        except Exception as ex:  # noqa
            log.error("%s: %s", reg, ex)
        db.commit()
        if i % 10 == 0:
            log.info("%d/%d notices processed, %d with metadata", i, len(todo), ok)
    log.info("EIS linked: done, %d/%d notices with metadata; attachments pending: %d", ok, len(todo),
             db.execute("SELECT COUNT(*) FROM documents WHERE document_type='attachment' AND extraction_status='pending'").fetchone()[0])
