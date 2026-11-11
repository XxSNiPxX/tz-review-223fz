"""Structured ingestion of a technical specification (DOCX first; PDF/XLSX fall back to text).

Output: a Document dict
  sections:   [{section_id, number, title, level, paragraphs:[{pid, text, section_id}]}]
  tables:     [{table_id, section_id, header:[...], rows:[{row_id, cells:{header->value}, raw:[...]}], kind}]
              kind = ATTRIBUTES (№ | характеристика | значение), ITEMS (наименование + ед.изм/кол-во/ОКПД2), WORKS, OTHER
  attributes: [{attr_id, name, value, table_id, row_id, section_id}]   from ATTRIBUTES tables and "Name: value" / "Name, ед — value" lines
  items:      [{item_id, name, unit, qty, okpd2, table_id, row_id}]
  fields:     subject, customer, address, deadline_text, warranty_text, okpd2_codes[], contract_kind (WORKS|GOODS|SERVICES|MIXED)
  clauses:    flat list compatible with checks.run_checks (clause_id, clause_text, section_id, anchor)
Every object carries an anchor (section number/title, table id, row number) so findings can point at the source.
"""
import re
from pathlib import Path
from .common import log

HEAD = re.compile(r"^\s*(?:(\d+(?:\.\d+)*)[.)]\s+|Раздел\s+(\d+)[.:]?\s+)(.{3,120})$")
KV_LINE = re.compile(r"^\s*([А-ЯЁA-Z][^:—–\n]{2,80}?)\s*(?::|—|–)\s*(.{1,200})$")
OKPD = re.compile(r"\b\d{2}\.\d{2}(?:\.\d{1,2}(?:\.\d{1,3})?)?\b")
ATTR_HDR = ("характеристик", "параметр", "показател", "наименование")
VALUE_HDR = ("значени", "требован", "описани")
ITEM_HDR = ("наименование", "товар", "работ", "услуг")
QTY_HDR = ("кол-во", "количество", "кол.")
UNIT_HDR = ("ед.", "единиц")
OKPD_HDR = ("окпд",)


def _docx(path):
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(path)
    body = d.element.body
    out = []
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            if p.text.strip():
                out.append(("p", p.text.strip(), (p.style.name if p.style is not None else "")))
        elif tag == "tbl":
            t = Table(child, d)
            rows = []
            for r in t.rows:
                cells, prev = [], None
                for c in r.cells:
                    tx = re.sub(r"\s+", " ", c.text).strip()
                    if tx == prev: continue          # merged cells repeat
                    cells.append(tx); prev = tx
                rows.append(cells)
            out.append(("t", rows, ""))
    return out


def _pdf_blocks(path):
    """PDF: tables via pdfplumber as table blocks, remaining text as paragraphs (table text removed to avoid duplicates)."""
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            tables = page.find_tables()
            if not tables:   # borderless tables (e.g. exported from Word without grid): text-alignment strategy, kept only if it looks tabular
                cand = page.find_tables(table_settings={"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 4, "intersection_tolerance": 6})
                tables = []
                for tb in cand:
                    rows = [r for r in tb.extract() if r and sum(1 for c in r if c and c.strip()) >= 2]
                    ncols = max((len(r) for r in rows), default=0)
                    if len(rows) >= 2 and 3 <= ncols <= 8 and sum(1 for r in rows if sum(1 for c in r if c and c.strip()) >= 2) >= len(rows) * 0.8:
                        tables.append(tb)
            table_bboxes = [tb.bbox for tb in tables]
            for tb in tables:
                rows = []
                for r in tb.extract():
                    cells, prev = [], None
                    for c in r:
                        tx = re.sub(r"\s+", " ", c or "").strip()
                        if tx == prev: continue
                        cells.append(tx); prev = tx
                    if any(cells): rows.append(cells)
                if rows: out.append(("t", rows, f"page{page_no}"))
            body = page
            for bb in table_bboxes:
                try: body = body.outside_bbox(bb)
                except Exception: pass
            text = body.extract_text() or ""
            # join wrapped lines into paragraphs: a new paragraph starts after sentence-final punctuation or at a numbered/bulleted line
            buf = ""
            for line in text.split("\n"):
                line = line.strip()
                if not line: continue
                starts_new = re.match(r"^(\d+(\.\d+)*[.)]\s|[•\-–—]\s|[А-ЯЁ][А-ЯЁ\s]{6,}$|Раздел\s)", line)
                if buf and (starts_new or re.search(r"[.;:!?]$", buf) or len(buf) > 1500):
                    out.append(("p", buf, f"page{page_no}")); buf = line
                else:
                    buf = (buf + " " + line).strip()
            if buf: out.append(("p", buf, f"page{page_no}"))
    return out


def _generic(path):
    if path.suffix.lower() == ".pdf":
        try:
            return _pdf_blocks(path)
        except Exception as ex:  # noqa
            log.warning("pdf table extraction failed (%s); flat text", ex)
    from . import extract_text
    reader = extract_text.READERS.get(path.suffix.lower())
    if not reader: raise ValueError(f"unsupported format {path.suffix}")
    out = []
    for page_no, text in reader(path):
        for line in text.split("\n"):
            if line.strip():
                out.append(("p", line.strip(), f"page{page_no}"))
    return out


def _table_kind(header):
    h = " ".join(header).lower()
    if any(k in h for k in OKPD_HDR) or (any(k in h for k in QTY_HDR) and any(k in h for k in ITEM_HDR)):
        return "WORKS" if "работ" in h and "товар" not in h else "ITEMS"
    if any(k in h for k in ATTR_HDR) and any(k in h for k in VALUE_HDR): return "ATTRIBUTES"
    if len(header) in (2, 3) and header and re.fullmatch(r"№|#|п/п|№ п/п", header[0].lower()): return "ATTRIBUTES"
    return "OTHER"


def _col(header, keys):
    for i, h in enumerate(header):
        if any(k in h.lower() for k in keys): return i
    return None


def parse(path: Path):
    path = Path(path)
    blocks = _docx(path) if path.suffix.lower() == ".docx" else _generic(path)
    doc = {"source": path.name, "sections": [], "tables": [], "attributes": [], "items": [], "clauses": [], "fields": {}}
    cur = {"section_id": "S0", "number": "0", "title": "Преамбула", "level": 0, "paragraphs": []}
    doc["sections"].append(cur)
    pid = tid = 0
    for kind, content, style in blocks:
        if kind == "p":
            m = HEAD.match(content)
            is_head = bool(m) and (len(content) < 120) and not content.rstrip().endswith((";", ",")) and not re.search(r"\bг\.|обл\.|ул\.|д\.\s*\d", content) and (
                "Heading" in style or (m.group(1) and m.group(1).count(".") == 0 and content[0].isdigit()) or m.group(2))
            if is_head:
                num = m.group(1) or m.group(2)
                cur = {"section_id": f"S{num}", "number": num, "title": m.group(3).strip(), "level": num.count(".") + 1, "paragraphs": []}
                doc["sections"].append(cur)
            pid += 1
            para = {"pid": f"P{pid}", "text": content, "section_id": cur["section_id"], "style": style}
            cur["paragraphs"].append(para)
            page = int(style[4:]) if style.startswith("page") and style[4:].isdigit() else None
            doc["clauses"].append({"clause_id": para["pid"], "clause_text": content, "section_id": cur["section_id"],
                                   "anchor": (f"стр. {page}, " if page else "") + f"раздел {cur['number']} «{cur['title'][:40]}», абзац {pid}", "page_number": page,
                                   "position_start": 0, "position_end": len(content)})
            kv = KV_LINE.match(content)
            if kv and len(kv.group(1)) < 60 and not is_head:
                doc["attributes"].append({"attr_id": f"A{para['pid']}", "name": kv.group(1).strip(), "value": kv.group(2).strip(),
                                          "table_id": None, "row_id": None, "section_id": cur["section_id"], "anchor": para["pid"]})
        else:
            tid += 1
            rows = [r for r in content if any(r)]
            if not rows: continue
            caption = None
            all_single = all(len(r) == 1 for r in rows)
            while not all_single and len(rows) > 1 and len(rows[0]) == 1 and len(rows[0][0]) < 300:   # short caption rows above the header
                caption = (caption + " / " if caption else "") + rows[0][0]; rows = rows[1:]
            header = rows[0]
            if all_single or len(rows) == 1 or max(len(h) for h in header) > 300:   # a layout table holding prose: treat cells as paragraphs
                for cell in (x for r in rows for x in r if x):
                    for line in re.split(r"\n|(?<=\.)\s+(?=[•\-–—]|[А-ЯЁ][а-яё]+\s+[а-яё])", cell):
                        if len(line.strip()) < 3: continue
                        pid += 1
                        doc["clauses"].append({"clause_id": f"P{pid}", "clause_text": line.strip(), "section_id": cur["section_id"],
                                               "anchor": f"раздел {cur['number']}, текст в таблице, абзац {pid}", "page_number": None,
                                               "position_start": 0, "position_end": len(line)})
                        cur["paragraphs"].append({"pid": f"P{pid}", "text": line.strip(), "section_id": cur["section_id"], "style": "table-cell"})
                continue
            if all(re.fullmatch(r"\d+", h.strip()) for h in header if h.strip()) and len(rows) > 1:   # "1 | 2 | 3" column-number row
                rows = rows[1:]; header = rows[0] if rows else header
            tkind = _table_kind(header)
            if tkind == "OTHER" and caption:
                cl = caption.lower()
                if "характеристик" in cl or "требования к качеству" in cl: tkind = "ATTRIBUTES"
                elif "наименование и количество" in cl or "спецификац" in cl: tkind = "ITEMS"
            # tables whose first row is data (no header words): treat 3-col as attributes
            table = {"table_id": f"T{tid}", "section_id": cur["section_id"], "header": header, "rows": [], "kind": tkind, "caption": caption,
                     "anchor": f"таблица {tid}" + (f" «{caption[:50]}»" if caption else f" в разделе {cur['number']}")}
            doc["tables"].append(table)
            name_c = _col(header, ("наименование", "характеристик", "параметр", "показател"))
            val_c = _col(header, VALUE_HDR)
            qty_c, unit_c, okpd_c = _col(header, QTY_HDR), _col(header, UNIT_HDR), _col(header, OKPD_HDR)
            subhead = None
            for ri, r in enumerate(rows[1:], 1):
                row = {"row_id": f"{table['table_id']}R{ri}", "raw": r, "cells": {header[i]: r[i] for i in range(min(len(header), len(r)))}}
                table["rows"].append(row)
                if len(r) == 1:                                   # sub-heading row inside the table
                    subhead = r[0]; continue
                text = " | ".join(x for x in r if x)
                doc["clauses"].append({"clause_id": row["row_id"], "clause_text": text, "section_id": cur["section_id"],
                                       "anchor": f"{table['anchor']}, строка {ri}" + (f" ({subhead})" if subhead else ""),
                                       "page_number": None, "position_start": 0, "position_end": len(text), "table_id": table["table_id"]})
                if tkind == "ATTRIBUTES" or (tkind == "OTHER" and len(r) == 3 and r[0].strip().rstrip(".").isdigit()):
                    name = r[name_c] if name_c is not None and name_c < len(r) else (r[1] if len(r) >= 2 else "")
                    val = r[val_c] if val_c is not None and val_c < len(r) else (r[-1] if len(r) >= 2 else "")
                    if name and val and name != val:
                        doc["attributes"].append({"attr_id": "A" + row["row_id"], "name": name, "value": val, "table_id": table["table_id"],
                                                  "row_id": row["row_id"], "section_id": cur["section_id"], "group": subhead,
                                                  "anchor": f"{table['anchor']}, строка {ri}"})
                elif tkind in ("ITEMS", "WORKS"):
                    name = r[name_c] if name_c is not None and name_c < len(r) else (r[1] if len(r) > 1 else r[0])
                    okpd = None
                    if okpd_c is not None and okpd_c < len(r): okpd = (OKPD.search(r[okpd_c]) or [None])[0] if OKPD.search(r[okpd_c]) else None
                    if okpd is None:
                        m = OKPD.search(text); okpd = m.group(0) if m else None
                    doc["items"].append({"item_id": "I" + row["row_id"], "name": name, "unit": r[unit_c] if unit_c is not None and unit_c < len(r) else None,
                                         "qty": r[qty_c] if qty_c is not None and qty_c < len(r) else None, "okpd2": okpd, "kind": tkind,
                                         "table_id": table["table_id"], "row_id": row["row_id"], "anchor": f"{table['anchor']}, строка {ri}"})
    _fields(doc)
    return doc


def _fields(doc):
    text = "\n".join(c["clause_text"] for c in doc["clauses"])
    f = doc["fields"]
    m = re.search(r"Предмет (?:закупки|договора|контракта)\s*[:：]\s*(.{5,200})", text)
    title_line = next((c["clause_text"] for c in doc["clauses"][:6] if re.search(r"техническое задание", c["clause_text"], re.I)), "")
    nxt = next((c["clause_text"] for c in doc["clauses"][1:6] if re.match(r"\s*на\s+(поставк|выполнени|оказани)", c["clause_text"], re.I)), "")
    f["subject"] = (m.group(1).strip() if m else (nxt or title_line)).strip()
    head = " ".join(c["clause_text"] for c in doc["clauses"][:8])[:1500]
    subj = (f["subject"] + " " + title_line + " " + nxt + " " + (head if not f["subject"] else "")).lower()
    works = bool(re.search(r"выполнени\w* работ|замен[аеу]|монтаж|ремонт|строительств|реконструкц", subj))
    goods = bool(re.search(r"поставк", subj))
    services = bool(re.search(r"оказани\w* услуг|обслуживани", subj))
    f["contract_kind"] = "MIXED" if (works and goods) else "WORKS" if works else "GOODS" if goods else "SERVICES" if services else "UNKNOWN"
    m = re.search(r"Заказчик\w*[^\n:]{0,40}:\s*([^\n|]{10,200})", text)
    if m and (re.match(r"\s*\d", m.group(1)) or re.search(r"\bобл\.|\bул\.|\bд\.\s*\d|пер\.", m.group(1))): m = None
    if not m:
        m = re.search(r"((?:Федеральное государственное|Государственное|Муниципальное|Акционерное общество|Общество с ограниченной|ООО|АО|ПАО|МУП|ГБУ|ГАУ|ОГАУ|ФГ[АБ]ОУ)[^\n|]{10,200})", text)
    f["customer"] = (m.group(1).strip() if m else None)
    m = re.search(r"(?:по адресу|Адрес (?:поставки|места нахождения|объекта))[:\s]*([^\n|]{10,160})", text, re.I)
    f["address"] = m.group(1).strip() if m else None
    m = re.search(r"(Срок (?:выполнения работ|поставки|оказания услуг)[^\n]{0,200})", text, re.I)
    f["deadline_text"] = m.group(1).strip() if m else None
    f["warranty_text"] = [c["clause_text"][:400] for c in doc["clauses"] if re.search(r"гарантийн\w+ срок", c["clause_text"], re.I)][:4]
    f["okpd2_codes"] = sorted({i["okpd2"] for i in doc["items"] if i.get("okpd2")} | set(OKPD.findall(" ".join(c["clause_text"] for c in doc["clauses"] if "ОКПД" in c["clause_text"]))))
    f["standards"] = sorted(set(re.findall(r"ГОСТ(?:\s*Р)?(?:\s*ИСО)?(?:\s*МЭК)?\s*\d[\d.\-]*(?:-\d{2,4})?", text)))
    f["n_sections"], f["n_tables"], f["n_attributes"], f["n_items"] = len(doc["sections"]), len(doc["tables"]), len(doc["attributes"]), len(doc["items"])
