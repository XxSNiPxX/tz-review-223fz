# Extraction fidelity check on the organisers' documents

Method (`scripts in session, reproducible`): every non-empty paragraph and every table cell of the raw DOCX (python-docx, merged
cells de-duplicated) is searched, whitespace-insensitively, in (a) the checkable clause texts and (b) the rendered document view.

| Document | Raw paragraphs | Raw table cells | Raw tables (rows) | Parsed tables (rows, kind) | Attributes | Items | Clauses | Character coverage in clauses | Missing from document view |
|---|---|---|---|---|---|---|---|---|---|
| Лифт, исходное | 97 | 188 | 3 (42, 22, 2) | 3 (41 ATTRIBUTES, 21 OTHER, 1 WORKS) | 34 | 1 | 153 | 99.1 % | **0** |
| Метрология, исходник | 6 | 214 | 4 (17, 16, 17, 5) | 3 (15 ITEMS, 15 ITEMS, 15 ATTRIBUTES) + 1 prose table emitted as paragraphs | 15 | 30 | 65 | 96.8 % | **0** |

The 0.9 % / 3.2 % not counted as *clauses* are table header rows, captions and group sub-headings («Кабина», «Двери шахты»,
«Наименование и количество поставляемого товара»). They are kept as table metadata and shown in the document view; they are
not requirements, so they are deliberately not checked as clauses. No paragraph of either document is lost. Headers and
footers of both files are empty.

Key fields recovered: subject and contract kind for both; the lift deadline sentence; all ОКПД2 codes (1 and 4); all cited
standards (8 and 3). Known limitation: Word auto-numbering is not part of the paragraph text, so a list numbered by Word
styles appears without its numbers (the two case documents use typed numbers, which are preserved).
