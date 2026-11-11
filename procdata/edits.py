"""Apply reviewer edits to the parsed document, re-check, and export the corrected DOCX.

The parsed Document (ingest.parse output) is the working copy; clause ids are stable (P<n>, T<n>R<m>), so an edit is
(clause_id, new_text). Table rows are edited as their cells joined by " | ". The corrected DOCX is produced by walking
the original file in ingest order (same as annotate.annotate_docx) and replacing paragraph / cell text.
"""
import json, re, uuid
from pathlib import Path
from .common import log

SEP = " | "


def apply_edit(doc, clause_id, new_text):
    """Mutates doc in place; returns (old_text, ok)."""
    for c in doc["clauses"]:
        if c["clause_id"] == clause_id:
            old = c["clause_text"]
            c["clause_text"] = new_text; c["normalized_text"] = re.sub(r"\s+", " ", new_text).lower()
            c["position_end"] = len(new_text); c["edited"] = True
            break
    else:
        return None, False
    for s in doc["sections"]:
        for p in s["paragraphs"]:
            if p["pid"] == clause_id: p["text"] = new_text
    for t in doc["tables"]:
        for r in t["rows"]:
            if r["row_id"] == clause_id:
                cells = [x.strip() for x in new_text.split(SEP)]
                if len(cells) == len(r["raw"]): r["raw"] = cells
                else: r["raw"] = cells + [""] * max(0, len(r["raw"]) - len(cells)) if len(cells) < len(r["raw"]) else cells[:len(r["raw"]) - 1] + [SEP.join(cells[len(r["raw"]) - 1:])]
                r["cells"] = {h: r["raw"][i] for i, h in enumerate(t["header"]) if i < len(r["raw"])}
    # attributes / items derived from table rows
    for a in doc["attributes"]:
        if a.get("row_id") == clause_id:
            for t in doc["tables"]:
                for r in t["rows"]:
                    if r["row_id"] == clause_id and len(r["raw"]) >= 2:
                        a["name"], a["value"] = (r["raw"][1], r["raw"][-1]) if len(r["raw"]) >= 3 else (r["raw"][0], r["raw"][1])
        elif a.get("anchor") == clause_id and a.get("table_id") is None:
            m = re.match(r"^\s*([А-ЯЁA-Z][^:—–\n]{2,80}?)\s*(?::|—|–)\s*(.{1,200})$", new_text)
            if m: a["name"], a["value"] = m.group(1).strip(), m.group(2).strip()
    for it in doc["items"]:
        if it.get("row_id") == clause_id:
            for t in doc["tables"]:
                for r in t["rows"]:
                    if r["row_id"] == clause_id:
                        raw = r["raw"]; it["name"] = raw[1] if len(raw) > 1 else raw[0]
                        m = re.search(r"\b\d{2}\.\d{2}(?:\.\d{1,2}(?:\.\d{1,3})?)?\b", SEP.join(raw)); it["okpd2"] = m.group(0) if m else it.get("okpd2")
    return old, True


def export_edited_docx(src: Path, edits_by_clause: dict, out: Path):
    """edits_by_clause: {clause_id: new_text}. Same body walk as annotate.annotate_docx."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(src))
    pid = tid = 0; n = 0

    def set_par(p, text):
        runs = p.runs
        if runs:
            runs[0].text = text
            for r in runs[1:]: r.text = ""
        else:
            p.add_run(text)

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            if not p.text.strip(): continue
            pid += 1
            if f"P{pid}" in edits_by_clause: set_par(p, edits_by_clause[f"P{pid}"]); n += 1
        elif tag == "tbl":
            tid += 1
            t = Table(child, d)
            rows_seen = []
            for r in t.rows:
                cells, prev, objs = [], None, []
                for c in r.cells:
                    tx = re.sub(r"\s+", " ", c.text).strip()
                    if tx == prev: continue
                    cells.append(tx); objs.append(c); prev = tx
                rows_seen.append((r, cells, objs))
            rows = [(r, c, o) for r, c, o in rows_seen if any(c)]
            if not rows: continue
            all_single = all(len(c) == 1 for _, c, _ in rows)
            idx = 0
            while not all_single and len(rows) - idx > 1 and len(rows[idx][1]) == 1 and len(rows[idx][1][0]) < 300: idx += 1
            if all_single or len(rows) - idx == 1 or max(len(h) for h in rows[idx][1]) > 300: continue
            header = rows[idx][1]
            if all(re.fullmatch(r"\d+", h.strip()) for h in header if h.strip()) and len(rows) - idx > 1: idx += 1
            for ri, (row, cells, objs) in enumerate(rows[idx + 1:], 1):
                key = f"T{tid}R{ri}"
                if key not in edits_by_clause: continue
                new_cells = [x.strip() for x in edits_by_clause[key].split(SEP)]
                for cell, txt in zip(objs, new_cells + [None] * (len(objs) - len(new_cells))):
                    if txt is None: continue
                    paras = cell.paragraphs
                    set_par(paras[0], txt)
                    for extra in paras[1:]:
                        for r in extra.runs: r.text = ""
                n += 1
    d.save(str(out)); log.info("edited docx %s: %d fragments replaced", out.name, n); return n
