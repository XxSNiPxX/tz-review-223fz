"""Produce a reviewed copy of the uploaded DOCX: problem fragments highlighted and Word comments attached,
so the procurement officer can pass the document back to its author. Clause ids are re-derived by walking the
document body in exactly the same order as ingest.parse (paragraph counter P<n>, tables T<n> with rows T<n>R<m>)."""
import re
from pathlib import Path
from .common import log

COLOR = {"ERROR": "RED", "RISK": "YELLOW", "NOTE": "GRAY_25"}
CATS = {"CONTRADICTION": "Противоречие", "INCORRECT_CHARACTERISTIC": "Некорректная характеристика", "COMPLETENESS": "Комплектность / полнота",
        "WRONG_OKPD2": "Код ОКПД 2", "WARRANTY": "Гарантийные условия", "STANDARDS": "Стандарты", "COMPETITION_RESTRICTION": "Ограничение конкуренции",
        "OUT_OF_SCOPE_PROVISION": "Не относится к ТЗ", "FORM": "Оформление"}
SEV = {"ERROR": "ОШИБКА", "RISK": "РИСК", "NOTE": "замечание"}


def _comment_text(f):
    disp = "требует проверки" if f["disposition"] == "INSUFFICIENT_EVIDENCE" else "подтверждено"
    lines = [f"[{SEV.get(f['severity'], f['severity'])} · {CATS.get(f.get('case_category'), f.get('case_category'))} · {disp}]", f["explanation"]]
    if f.get("proposed_text"): lines.append("Исправить: " + f["proposed_text"])
    ev = [o for o in f.get("evidence_objects", []) if o["type"] != "lexicon"]
    if ev: lines.append("Основание: " + "; ".join(o["id"] for o in ev[:3]))
    return "\n".join(lines)[:1800]


def annotate_docx(src: Path, findings, out: Path, author="Проверка ТЗ"):
    import docx
    from docx.enum.text import WD_COLOR_INDEX
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(str(src))
    by = {}
    for f in findings:
        if f.get("clause_id"): by.setdefault(f["clause_id"], []).append(f)
    pid = tid = 0; n_marked = 0
    HEAD = re.compile(r"^\s*(?:(\d+(?:\.\d+)*)[.)]\s+|Раздел\s+(\d+)[.:]?\s+)(.{3,120})$")

    def mark(paragraphs, fs):
        nonlocal n_marked
        runs = [r for p in paragraphs for r in p.runs if r.text.strip()]
        if not runs: return
        sev = min(fs, key=lambda f: ["ERROR", "RISK", "NOTE"].index(f["severity"]))["severity"]
        for r in runs: r.font.highlight_color = getattr(WD_COLOR_INDEX, COLOR[sev])
        try:
            d.add_comment(runs, text="\n\n".join(_comment_text(f) for f in fs), author=author, initials="ТЗ")
        except Exception as ex:  # noqa  older python-docx without comments: highlight only
            log.warning("comment failed: %s", ex)
        n_marked += 1

    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            if not p.text.strip(): continue
            pid += 1
            fs = by.get(f"P{pid}")
            if fs: mark([p], fs)
        elif tag == "tbl":
            tid += 1
            t = Table(child, d)
            rows_seen = []
            for r in t.rows:
                cells, prev = [], None
                for c in r.cells:
                    tx = re.sub(r"\s+", " ", c.text).strip()
                    if tx == prev: continue
                    cells.append(tx); prev = tx
                rows_seen.append((r, cells))
            rows = [(r, c) for r, c in rows_seen if any(c)]
            if not rows: continue
            all_single = all(len(c) == 1 for _, c in rows)
            # mirror ingest: pop short single-cell caption rows, then a numeric column-index row
            idx = 0
            while not all_single and len(rows) - idx > 1 and len(rows[idx][1]) == 1 and len(rows[idx][1][0]) < 300: idx += 1
            if all_single or len(rows) - idx == 1 or max(len(h) for h in rows[idx][1]) > 300:
                continue   # prose table: its text was emitted as paragraphs P<n> by ingest; counters there are not reproducible here
            header = rows[idx][1]
            if all(re.fullmatch(r"\d+", h.strip()) for h in header if h.strip()) and len(rows) - idx > 1: idx += 1
            for ri, (row, cells) in enumerate(rows[idx + 1:], 1):
                fs = by.get(f"T{tid}R{ri}")
                if fs:
                    paras = [p for c in row.cells for p in c.paragraphs]
                    mark(paras, fs)
    d.save(str(out))
    log.info("annotated %s: %d fragments marked", out.name, n_marked)
    return n_marked
