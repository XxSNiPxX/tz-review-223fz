# Pitch (3 minutes) and judge Q&A

Deck: `docs/presentation.pdf`. Slides 1–6 are the pitch. Everything after "Запасные слайды" is backup, opened only when a question needs it.

## 3-minute script (≈ 30 s per slide)

| # | Time | Say (RU) | Meaning (EN) |
|---|---|---|---|
| 1 | 0:00–0:20 | «Мы сделали систему, которая проверяет ТЗ на закупку по 223-ФЗ: находит ошибки, обосновывает их нормой и практикой ФАС и исправляет. Работает полностью локально, без сторонних LLM. На эталонах — все 27 правок эксперта и ни одной ложной ошибки.» | What it is plus the headline numbers |
| 2 | 0:20–0:50 | «Обычно ТЗ вставляют в ChatGPT. Документ уходит в чужое облако, нормы модель берёт по памяти и выдумывает. Мы сделали наоборот: каждое замечание опирается на нашу базу — 223-ФЗ по частям, 420 доводов ФАС, ОКПД2 — и привязано к конкретному фрагменту. 7B-модель без базы у нас переписала "не менее 7" в "ровно 7" — поэтому LLM у нас только формулирует.» | Why not ChatGPT |
| 3 | 0:50–1:30 | **Live demo if possible** (see below). Otherwise: «Документ пронумерован, каждая проблема подсвечена. Клик по ссылке ¶6 прокручивает к фрагменту. "Исправить" показывает было/станет, после подтверждения документ перепроверяется, а правка попадает в раздел "Исправлено", как diff в GitHub.» | What the user sees |
| 4 | 1:30–2:00 | «Около 30 детерминированных проверок плюс модели: RuBERT определяет роль пункта, e5 ищет нормы и решения ФАС, Qwen-7B формулирует пояснения. Если данных для вывода нет — пишем "требует проверки", а не "нарушение".» | Architecture |
| 5 | 2:00–2:35 | «Эталоны: два документа организаторов и два наших из других областей — 27 из 27 обязательных правок, 0 ложных. 32 автоисправления — все снимают замечание. Система учится на оценках и правках экспертов, но новая модель включается, только если на эталонах она не хуже: "вредные" отзывы мы отклонили автоматически.» | Results and learning |
| 6 | 2:35–3:00 | «Всё открыто: три команды — и у вас свой экземпляр. Работает даже на сервере с 709 МБ памяти. Попробуйте: демо-вход, пример документа, "Исправить автоматически". Спасибо!» | Close |

**Live demo (40 s, rehearse it):** https://185-17-3-218.sslip.io → «Войти в демо-режиме» → sample «Вычислительная техника» → click finding 4 (Lenovo, no equivalent) → «Исправить автоматически» → show was/becomes → apply → show «Исправлено». Keep slide 3 open in a second tab in case the network fails.

## Likely questions and answers

### About the solution

**1. Why not just use an LLM (GigaChat / YandexGPT / ChatGPT)?**
Three reasons:
- customer documents can't leave the organisation;
- an LLM invents legal references and quietly changes numbers ("не менее 7" became "ровно 7" in our test);
- the result isn't reproducible.

Rules plus a knowledge base give the same answer every time, and every finding has a source. The LLM is only used to word explanations, and its answer is discarded if it cites a norm that isn't in our base or adds numbers that aren't in the text.
RU: «LLM у нас не принимает решений — только формулирует, и её ответ проверяется.»

**2. Where exactly does the LLM run in the demo?**
Honest answer: the public demo runs on a small VPS (1 vCPU, 709 MB RAM) in **lite mode, without the LLM**. There, explanations come from rule templates plus the knowledge base. Detection quality on the gold set is the same, because the LLM doesn't detect anything.

The full mode (Qwen2.5-7B, 4-bit, llama.cpp) needs about 10 GB RAM. It runs on our machine and would run on an MIPT server. On CPU it takes about a minute per explanation.

**3. How do you know a finding is correct? How do you avoid false positives?**
- Every finding has evidence: a law part, FAS decisions, or the ОКПД2 classifier.
- When there isn't enough data, the status is «требует проверки», not «нарушение».
- We measure false positives on the expert-corrected versions of the documents: 0.

**4. How do you understand context, e.g. "4 остановки" needs no unit?**
An attribute dictionary (`kb/attribute_units.json`) classifies each characteristic as:
- a count (stops, pieces);
- dimensionless (accuracy class);
- a physical quantity (mass, temperature).

Only physical quantities without a unit are flagged, and the system suggests the expected unit.

**5. How does the auto-fix work, and can it break something?**
- There is a rewrite rule for each kind of problem. The ОКПД2 code is picked by item name from all 21,081 codes (TF-IDF). The LLM is only a fallback.
- Before a fix is offered, the checks are re-run on the new text. If the problem would remain, the fix isn't offered.
- After the user confirms, the whole document is re-checked.

On the gold set: 32 of 32 proposed fixes cleared their finding, and 0 created new problems.

**6. What are the models? Did you train anything yourselves?**

| Model | Role | Trained by us? |
|---|---|---|
| RuBERT-tiny2 (29M) | clause role (requirement / contract term / legal reference) | yes, fine-tuned on 46,752 clauses from real ЕИС documents, about 7 min on CPU |
| multilingual-e5-small | search for similar norms and FAS cases | used as is |
| Qwen2.5-7B-Instruct Q4 | explanations, fallback fixes | used as is |
| finding filter (TF-IDF + logistic regression) | retrained on expert feedback | yes, automatically |

Be ready for this one: the RuBERT labels are *weak* (generated by rules), so its accuracy of 0.68 / macro-F1 0.72 is measured against those labels. It's a helper signal, not the main detector.

**7. How does it learn, and what stops bad feedback from making it worse?**
- Every vote, category correction, "missed problem" report and edit (before text, after text, method, whether it cleared the finding) is stored in SQLite and exported as JSONL.
- Every 30 minutes, if there are at least 10 new verdicts, the filter is retrained.
- The new model passes a **gate**: on the gold set it must keep all mandatory findings, add no false positives, and downgrade nothing.

We tested this with "harmful" feedback that rejected real contradictions. The candidate would have dropped from 27 to 17 kept findings, so the gate rejected it automatically.

**8. Where does your data come from? Is it legal?**
All of it is public:
- ЕИС (zakupki.gov.ru): 321 procurements, 46,752 ТЗ clauses;
- the FAS decisions base: 437 cases, 420 complaint arguments;
- law texts from КонсультантПлюс, Гарант and RusLawOD;
- the ОКПД2 classifier.

Laws are in the public domain. RusLawOD is CC BY-NC, which suits a non-commercial hackathon. The data is collected once with our own collectors; reviewing a document makes no network calls.

### About the evaluation (judges will push here)

**9. 27/27 on 4 documents isn't much. Isn't this overfitted to the examples?**
Agree that the set is small, and say so openly.
- The organisers gave 2 document pairs. We added 2 of our own documents from different areas (cleaning services, IT hardware) specifically to check that the logic isn't tuned to the lift and metrology examples.
- The checks are general rules (units, ОКПД2, warranty basis by contract type, brand without equivalent), not string matches on the sample text.
- The next step is a larger labelled set from real FAS complaints.

RU: «Да, эталон маленький — поэтому мы и добавили документы из других областей и сделали дообучение на реальных правках экспертов.»

**10. What is recall/precision on real documents, not your gold set?**
We don't have expert labels for real ЕИС documents yet, so we can't claim a number. That's exactly what the feedback loop is for: every expert verdict becomes a labelled example.

**11. What does the system miss? What can't it do?**
- It doesn't have each customer's own procurement regulations (Положения о закупке) or the SME list (ПП 1352), so those places get «требует проверки».
- There are no market catalogues, so "excessive requirements" are judged by signs, not by real market data.
- The LLM is slow on CPU.

These are on the "next" slide.

### About practicality

**12. How fast is it? Can it run at our organisation?**
- A check takes 1–3 s per document without the LLM.
- Setup is one Docker command plus `./setup.sh`.
- Lite mode runs in under 1 GB RAM.
- Login works through Yandex ID or Google, and access can be restricted to a domain (e.g. phystech.edu).

**13. Which formats are supported?**
DOCX, DOC, RTF, ODT, PDF (text-based) and XLSX. Scanned PDFs without a text layer aren't supported (no OCR yet).

**14. What does the user get at the end?**
- the corrected DOCX;
- a DOCX with highlights and Word comments;
- a conclusion as DOCX/HTML;
- JSON for integration.

**15. Why 223-ФЗ and not 44-ФЗ? Can it be extended?**
The task was about 223-ФЗ, but the knowledge base already contains 44-ФЗ by part. Most checks (units, ОКПД2, brand without equivalent, standards) apply to both laws; only the legal references and some rules change.

**16. What's next if you get support?**
1. Customers' procurement regulations from ЕИС, to check against internal rules.
2. Expert labelling of about 100 FAS decisions, so trained classifiers can replace some rules.
3. A market catalogue for one product class, to check excessive requirements with data.
4. LoRA fine-tuning of the LLM on the stored expert edits.

**17. What did each team member do?**
*Prepare your own answer:* who built data collection, the checks, the UI and the deploy. Judges like a clear split.

### Traps to avoid
- Don't say "AI finds violations." Say: "rules find, the base justifies, the LLM explains."
- Don't claim the demo server uses the LLM. It runs in lite mode.
- Don't claim the system runs on an MIPT server today. It runs on our own VPS and is *ready to be deployed* on an MIPT or customer server.
- If you don't know an answer: «Хороший вопрос — это мы не измеряли, но вот как бы мы это проверили…»
