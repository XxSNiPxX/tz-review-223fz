"""Turn downloaded attachments (PDF/DOCX/XLSX) into document_sections and clauses.

Clause splitting is deliberately simple: numbered items ("1.", "2.3.", "п. 4") and table rows.
Good enough as the unit that annotators and models work on; refine later.
"""
import re
from pathlib import Path
from .common import log, upsert

NUM_ITEM = re.compile(r"(?m)^\s*(?:\d+(?:\.\d+)*[.)]|[-•–])\s+")


def _pdf(path):
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, p in enumerate(pdf.pages, 1):
            text = p.extract_text() or ""
            tables = p.extract_tables() or []
            for t in tables:
                for row in t:
                    cells = [c.strip() for c in row if c]
                    if cells:
                        text += "\n" + " | ".join(cells)
            pages.append((i, text))
    return pages


def _docx(path):
    import docx
    d = docx.Document(path)
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return [(1, "\n".join(parts))]


def _xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return [(1, "\n".join(parts))]


READERS = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx}


def split_clauses(text):
    """Return (start, end, clause_text) chunks."""
    idx = [m.start() for m in NUM_ITEM.finditer(text)]
    if not idx:
        idx = [m.end() for m in re.finditer(r"\n\s*\n", text)]
    bounds = [0] + idx + [len(text)]
    out = []
    for a, b in zip(bounds, bounds[1:]):
        chunk = text[a:b].strip()
        if len(chunk) >= 20:
            out.append((a, b, chunk))
    return out


def extract_all(db, cfg, limit=None):
    rows = db.execute("SELECT document_id, procurement_id, storage_path FROM documents "
                      "WHERE document_type='attachment' AND extraction_status='downloaded'"
                      + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    for r in rows:
        path = Path(r["storage_path"])
        reader = READERS.get(path.suffix.lower())
        if not reader:
            db.execute("UPDATE documents SET extraction_status='failed', error='unsupported_format' WHERE document_id=?",
                       (r["document_id"],)); continue
        try:
            pages = reader(path)
        except Exception as ex:  # noqa
            log.error("extract %s: %s", path, ex)
            db.execute("UPDATE documents SET extraction_status='failed', error=? WHERE document_id=?",
                       (str(ex)[:200], r["document_id"])); continue
        n = 0
        for page_no, text in pages:
            sec_id = f"{r['document_id']}:p{page_no}"
            upsert(db, "document_sections", {"section_id": sec_id, "document_id": r["document_id"],
                                             "section_text": text, "page_start": page_no, "page_end": page_no}, "section_id")
            for a, b, chunk in split_clauses(text):
                n += 1
                upsert(db, "clauses", {
                    "clause_id": f"{r['document_id']}:c{page_no}_{a}", "document_id": r["document_id"],
                    "section_id": sec_id, "procurement_id": r["procurement_id"], "clause_text": chunk,
                    "normalized_text": re.sub(r"\s+", " ", chunk).lower(), "page_number": page_no,
                    "position_start": a, "position_end": b}, "clause_id")
        db.execute("UPDATE documents SET extraction_status='extracted' WHERE document_id=?", (r["document_id"],))
        db.commit()
        log.info("%s -> %d clauses", path.name, n)
