"""Report rendering: document view for the UI (clauses with anchors), a standalone printable HTML report, and a DOCX report."""
import html, json, datetime, re
from pathlib import Path

CATS = {"CONTRADICTION": "Противоречие", "INCORRECT_CHARACTERISTIC": "Некорректная характеристика", "COMPLETENESS": "Комплектность / полнота",
        "WRONG_OKPD2": "Код ОКПД 2", "WARRANTY": "Гарантийные условия", "STANDARDS": "Стандарты", "COMPETITION_RESTRICTION": "Ограничение конкуренции",
        "OUT_OF_SCOPE_PROVISION": "Не относится к ТЗ", "FORM": "Оформление"}
SEV = {"ERROR": "Ошибка", "RISK": "Риск", "NOTE": "Замечание"}
DISP = {"FLAGGED": "подтверждено правилом", "INSUFFICIENT_EVIDENCE": "требует проверки", "PASSED": "ок"}


def document_view(doc, clauses):
    """Ordered blocks for rendering. Every paragraph gets a number «¶n» and every table row «Т<t>.<r>»; each block also
    carries the anchor string used in findings, so the UI can turn any reference into a scroll-to link."""
    anchors = {c["clause_id"]: c.get("anchor") for c in clauses}
    if not doc:
        return [{"type": "p", "clause_id": c["clause_id"], "text": c["clause_text"], "num": f"¶{i}", "anchor": c.get("anchor")} for i, c in enumerate(clauses, 1)]
    blocks, emitted, pn = [], set(), 0
    tnum = {t["table_id"]: i for i, t in enumerate(doc["tables"], 1)}
    for s in doc["sections"]:
        if s["section_id"] != "S0" or s["paragraphs"]:
            blocks.append({"type": "h", "text": (s["number"] + ". " if s["number"] != "0" else "") + s["title"], "section_id": s["section_id"]})
        for p in s["paragraphs"]:
            pn += 1
            blocks.append({"type": "p", "clause_id": p["pid"], "text": p["text"], "num": f"¶{pn}", "anchor": anchors.get(p["pid"])}); emitted.add(p["pid"])
        for t in doc["tables"]:
            if t["section_id"] != s["section_id"] or t["table_id"] in emitted: continue
            emitted.add(t["table_id"]); k = tnum[t["table_id"]]
            blocks.append({"type": "table", "table_id": t["table_id"], "num": f"Т{k}", "caption": t.get("caption"), "header": t["header"], "anchor": t.get("anchor"),
                           "rows": [{"clause_id": r["row_id"], "cells": r["raw"], "num": f"Т{k}.{i}", "anchor": anchors.get(r["row_id"])} for i, r in enumerate(t["rows"], 1)]})
    return blocks


def _esc(x): return html.escape(str(x if x is not None else ""))


def render_html(report):
    con, fs = report.get("conclusion") or {}, report["findings"]
    by = {}
    for f in fs: by.setdefault(f.get("case_category", "?"), []).append(f)
    rows = "".join(f"<tr><td>{_esc(CATS.get(k, k))}</td><td>{len(v)}</td><td>{sum(x['severity']=='ERROR' and x['disposition']=='FLAGGED' for x in v)}</td>"
                   f"<td>{sum(x['severity']=='RISK' and x['disposition']=='FLAGGED' for x in v)}</td><td>{sum(x['disposition']=='INSUFFICIENT_EVIDENCE' for x in v)}</td></tr>" for k, v in by.items())
    items = []
    order = {"ERROR": 0, "RISK": 1, "NOTE": 2}
    for i, f in enumerate(sorted(fs, key=lambda x: (order.get(x["severity"], 3), x["disposition"] != "FLAGGED")), 1):
        ev = "".join(f"<li><code>{_esc(o['id'])}</code> <span class=muted>({_esc(o['type'])})</span>: {_esc(o['text'][:500])}</li>" for o in f.get("evidence_objects", []) if o["type"] != "lexicon")
        items.append(f"""<section class="f {f['severity']}">
<h3>{i}. {_esc(CATS.get(f.get('case_category'), f.get('case_category')))} <span class="pill {f['severity']}">{SEV.get(f['severity'], f['severity'])}</span> <span class="pill">{DISP.get(f['disposition'], f['disposition'])}</span></h3>
<p class="where">Где: {_esc(', '.join(f.get('anchors') or []) or (('стр. ' + str(f['page'])) if f.get('page') else f.get('clause_id') or ''))}</p>
<blockquote>{_esc(f['clause_text'])}</blockquote>
<p><b>Почему это проблема.</b> {_esc(f['explanation'])}</p>
{('<p><b>Предлагаемая корректировка.</b> ' + _esc(f['proposed_text']) + '</p>') if f.get('proposed_text') else ''}
{('<p><b>Основание.</b></p><ul>' + ev + '</ul>') if ev else '<p class=muted>Основание: внутренние правила проверки (словарь/структура документа).</p>'}
</section>""")
    d = con.get("document") or {}
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Заключение по ТЗ</title>
<style>
body{{font:14px/1.5 "Times New Roman",Georgia,serif;color:#111;max-width:860px;margin:32px auto;padding:0 20px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin:26px 0 8px;border-bottom:1px solid #999;padding-bottom:4px}} h3{{font-size:15px;margin:0 0 4px}}
.muted{{color:#666}} table{{border-collapse:collapse;width:100%;margin:8px 0}} td,th{{border:1px solid #bbb;padding:4px 8px;text-align:left}}
.f{{border-left:4px solid #999;padding:8px 12px;margin:14px 0;page-break-inside:avoid}} .f.ERROR{{border-color:#b42318}} .f.RISK{{border-color:#b54708}} .f.NOTE{{border-color:#667}}
.pill{{display:inline-block;font:12px sans-serif;border:1px solid #999;border-radius:10px;padding:0 8px;margin-left:6px;vertical-align:middle}} .pill.ERROR{{color:#b42318;border-color:#b42318}} .pill.RISK{{color:#b54708;border-color:#b54708}}
blockquote{{margin:6px 0;padding:6px 10px;background:#f4f4f4;border-left:3px solid #ccc;font-style:italic}} .where{{font-size:13px;color:#444;margin:0 0 4px}}
.verdict{{font-size:16px;font-weight:bold;padding:10px 12px;border:2px solid {'#b42318' if con.get('errors') else '#067647'};margin:12px 0}}
code{{font:12px monospace;background:#eee;padding:0 3px}} @media print{{body{{margin:0}} .f{{break-inside:avoid}}}}
</style></head><body>
<h1>Заключение по результатам проверки технического задания</h1>
<div class="muted">Документ: {_esc(report.get('source'))} · дата проверки: {_esc(report.get('reviewed_at'))} · база знаний: {_esc(report.get('kb_release', {}).get('legal_rules'))} норм, {_esc(report.get('kb_release', {}).get('fas_findings'))} прецедентов ФАС · {'с объяснениями LLM' if report.get('llm_used') else 'без LLM'}</div>
<div class="verdict">{_esc(con.get('verdict'))}</div>
<table><tr><th>Предмет закупки</th><td>{_esc(d.get('subject'))}</td></tr><tr><th>Вид договора</th><td>{_esc(d.get('contract_kind'))}</td></tr>
<tr><th>Заказчик</th><td>{_esc(d.get('customer'))}</td></tr><tr><th>Структура</th><td>разделов {_esc(d.get('sections'))}, таблиц {_esc(d.get('tables'))}, позиций {_esc(d.get('items'))}, пунктов {_esc(report.get('n_clauses'))}</td></tr>
<tr><th>Коды ОКПД2</th><td>{_esc(', '.join(d.get('okpd2_codes') or []) or '—')}</td></tr><tr><th>Стандарты</th><td>{_esc(', '.join(d.get('standards') or []) or '—')}</td></tr></table>
<h2>Сводка рисков</h2>
<p>Ошибок: <b>{con.get('errors', 0)}</b> · рисков: <b>{con.get('risks', 0)}</b> · требует ручной проверки: <b>{con.get('manual_review', 0)}</b> · замечаний по оформлению: {con.get('notes', 0)}</p>
<table><tr><th>Категория</th><th>Всего</th><th>Ошибки</th><th>Риски</th><th>На проверку</th></tr>{rows}</table>
<h2>Найденные проблемы</h2>
{''.join(items) or '<p>Проблем не выявлено.</p>'}
<h2>Методика</h2>
<p class="muted">Проверка выполнена детерминированными правилами по структуре документа (разделы, таблицы характеристик, спецификации), с опорой на внутреннюю базу: нормы 223-ФЗ/44-ФЗ по частям статей, решения ФАС по доводам, классификатор ОКПД2 (ОК 034-2014), реестр стандартов. Пункты со статусом «требует проверки» — это места, где система не располагает достаточными данными для однозначного вывода; они не являются установленными нарушениями. Система не запрашивает внешние сервисы.</p>
</body></html>"""


def render_docx(report, path: Path):
    import docx
    from docx.shared import Pt, RGBColor
    con, fs = report.get("conclusion") or {}, report["findings"]
    d = docx.Document()
    st = d.styles["Normal"]; st.font.name = "Times New Roman"; st.font.size = Pt(11)
    d.add_heading("Заключение по результатам проверки технического задания", level=1)
    d.add_paragraph(f"Документ: {report.get('source')}. Дата проверки: {report.get('reviewed_at')}. База знаний: {report.get('kb_release', {}).get('legal_rules')} норм, {report.get('kb_release', {}).get('fas_findings')} прецедентов ФАС.")
    p = d.add_paragraph(); r = p.add_run(con.get("verdict", "")); r.bold = True; r.font.size = Pt(13)
    dd = con.get("document") or {}
    t = d.add_table(rows=0, cols=2); t.style = "Table Grid"
    for k, v in [("Предмет закупки", dd.get("subject")), ("Вид договора", dd.get("contract_kind")), ("Заказчик", dd.get("customer")),
                 ("Коды ОКПД2", ", ".join(dd.get("okpd2_codes") or []) or "—"), ("Стандарты", ", ".join(dd.get("standards") or []) or "—"),
                 ("Ошибок / рисков / на проверку", f"{con.get('errors', 0)} / {con.get('risks', 0)} / {con.get('manual_review', 0)}")]:
        c = t.add_row().cells; c[0].text = k; c[1].text = str(v or "")
    d.add_heading("Найденные проблемы", level=2)
    order = {"ERROR": 0, "RISK": 1, "NOTE": 2}
    for i, f in enumerate(sorted(fs, key=lambda x: (order.get(x["severity"], 3), x["disposition"] != "FLAGGED")), 1):
        h = d.add_paragraph(); rr = h.add_run(f"{i}. {CATS.get(f.get('case_category'), f.get('case_category'))} — {SEV.get(f['severity'], f['severity'])}, {DISP.get(f['disposition'], f['disposition'])}"); rr.bold = True
        if f["severity"] == "ERROR": rr.font.color.rgb = RGBColor(0xB4, 0x23, 0x18)
        d.add_paragraph("Где: " + (", ".join(f.get("anchors") or []) or (f"стр. {f['page']}" if f.get("page") else f.get("clause_id") or "")))
        q = d.add_paragraph(f"«{f['clause_text'][:700]}»"); q.runs[0].italic = True
        d.add_paragraph("Почему это проблема: " + f["explanation"])
        if f.get("proposed_text"): d.add_paragraph("Предлагаемая корректировка: " + f["proposed_text"])
        ev = [o for o in f.get("evidence_objects", []) if o["type"] != "lexicon"]
        if ev:
            d.add_paragraph("Основание:")
            for o in ev[:4]: d.add_paragraph(f"{o['id']} ({o['type']}): {o['text'][:400]}", style="List Bullet")
    d.add_heading("Методика", level=2)
    d.add_paragraph("Проверка выполнена детерминированными правилами по структуре документа с опорой на внутреннюю базу норм 223-ФЗ/44-ФЗ, решений ФАС, классификатора ОКПД2 и реестра стандартов. Пункты «требует проверки» не являются установленными нарушениями. Внешние сервисы не используются.")
    d.save(str(path)); return path
