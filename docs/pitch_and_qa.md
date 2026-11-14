# Pitch (3 minutes) and judge Q&A

Deck: `docs/presentation.pdf`. Slides 1–6 are the pitch. Everything after "Запасные слайды" is backup, opened only when a question needs it.

**Rule:** don't claim scores. The organisers' brief gives no number of problems and no metric, so any "N out of N" would be our own count and invites attack. Show concrete findings and the live demo instead.

## 3-minute script (≈ 30 s per slide)

| # | Time | Say (RU) | Meaning (EN) |
|---|---|---|---|
| 1 | 0:00–0:20 | «Мы сделали систему, которая подсвечивает проблемы в ТЗ на закупку по 223-ФЗ, показывает основание и предлагает исправление. Девять категорий проблем из задания, 1–3 секунды на документ, и документ не покидает сервер — никаких внешних API.» | What it is |
| 2 | 0:20–0:50 | «Облачный чат-бот получает документ заказчика, а ссылки на нормы берёт по памяти — их надо перепроверять. У нас основания берутся из собранной базы: 223-ФЗ по частям, доводы из решений ФАС, ОКПД2. Проверки детерминированные, а LLM только поясняет: в нашем тесте 7B-модель без базы переписала «не менее 7» в «ровно 7».» | Why not a chatbot |
| 3 | 0:50–1:30 | **Live demo if possible** (see below). Otherwise: «Документ пронумерован, проблемы подсвечены. Ссылка ¶6 прокручивает к фрагменту. «Исправить» показывает было/станет, после подтверждения документ перепроверяется, правка попадает в раздел «Исправлено».» | What the user sees |
| 4 | 1:30–2:00 | «Около 30 проверок, база знаний и модели: RuBERT — роль пункта, e5 — поиск норм и решений ФАС, Qwen-7B — пояснения. Если данных не хватает, система пишет «требует проверки», а не «нарушение».» | Architecture |
| 5 | 2:00–2:35 | «Пример — ТЗ организаторов на замену лифта. Система показывает: в таблице лифт пассажирский, а в предмете закупки — грузовой; 300 кг против 500; гарантия на работы от товарной накладной вместо КС-2; поставка лифта без позиции с кодом товара; ГОСТ без «Р» — как «требует проверки». И система учится на правках экспертов, но новая версия включается, только если на контрольных документах она не хуже.» | Concrete example plus learning |
| 6 | 2:35–3:00 | «Всё открыто: три команды — и у вас свой экземпляр; демо работает на сервере с 709 МБ памяти. Дальше — оценка на размеченных жалобах ФАС и Положения о закупке заказчиков. Попробуйте: демо-вход, пример, «Исправить автоматически». Спасибо!» | Close |

**Live demo (40 s, rehearse it):** https://185-17-3-218.sslip.io → «Войти в демо-режиме» → sample «Вычислительная техника» → finding 4 (Lenovo, no equivalent) → «Исправить автоматически» → was/becomes → apply → «Исправлено». Keep slide 3 open as a fallback in case the network fails.

## Numbers you may say (all verifiable)

| Claim | Basis |
|---|---|
| 9 categories | the problem categories listed in the brief, all covered by checks |
| 1–3 s per document | without the LLM |
| 0 external APIs | reviewing a document makes no network calls |
| 709 MB | RAM of the demo server (lite mode, **no LLM**) |
| 420 FAS arguments, 21,081 ОКПД2 codes, 46,752 ЕИС clauses | size of the collected knowledge base |

**Don't volunteer scores.** If asked "how did you evaluate?", see question 3.

## Likely questions and answers

### About the solution

**1. Why not just use an LLM (GigaChat / YandexGPT / ChatGPT)?**
Three reasons:
- customer documents shouldn't leave the organisation;
- an LLM's legal references come from memory and must be re-checked, and in our test it changed "не менее 7" into "ровно 7";
- the result isn't reproducible.

So rules plus the knowledge base decide, and the LLM only words explanations. An answer that cites a norm outside our base is discarded.

**2. Where is the LLM in the demo?**
The public demo runs on a small VPS (1 vCPU, 709 MB RAM) in **lite mode, without the LLM**. Explanations there come from templates plus the knowledge base. Detection is the same, because the LLM doesn't detect anything. The full mode (Qwen2.5-7B, 4-bit) needs about 10 GB RAM and takes about a minute per explanation on CPU. It runs on our machine.

**3. How did you evaluate it?**
The organisers gave two documents, each with an expert-corrected version. We compared the system's findings with the places the expert changed (`eval_case.py`) and checked that it raises no confirmed errors on the corrected versions. If pushed for details:
- On those two documents, every place the expert changed gets a finding: on the lift, 4 as an error and 2 as "требует проверки"; on metrology, all 4 as "требует проверки".
- Two things are only partly caught: the lift's works code (.120→.110), and 2 of 5 ОКПД2 codes in metrology, which are valid codes but not the best fit.

We don't present this as a score: the set is tiny, and the brief didn't define a metric.

**4. What does it miss?**
- "Valid but not the best" ОКПД2 codes. We only catch codes that are too generic, don't exist, or are the wrong kind.
- Customers' own procurement regulations and the SME list are not in the base yet, so those places get "требует проверки".
- There are no market catalogues, so excessive requirements are judged by wording, not prices.

**5. Do you have false positives?**
On the expert-corrected versions there are no confirmed errors. Some "требует проверки" notes remain (e.g. generic «…190» codes the expert kept, standards without a year), and arguably some of them are real. That's why ambiguous cases are "check", not "violation".

**6. How does it understand context, e.g. "4 остановки" needs no unit?**
An attribute dictionary classifies each characteristic as a count, dimensionless, or a physical quantity. Only physical quantities without a unit are flagged, and the expected unit is suggested.

**7. How does the auto-fix work, and can it break something?**
- There is a rewrite rule per problem type. ОКПД2 codes are picked by item name from 21,081 codes. The LLM is a fallback.
- Before a fix is offered, the checks are re-run on the new text. If the problem would remain, the fix isn't offered.
- After the user confirms, the whole document is re-checked.

That re-check uses our own rules; an expert didn't grade the wording. Kits and their contents aren't fixed automatically.

**8. What models? Did you train anything?**

| Model | Role | Trained by us? |
|---|---|---|
| RuBERT-tiny2 (29M) | clause role (requirement / contract term / legal reference) | fine-tuned on 46,752 clauses from ЕИС documents, about 7 min on CPU |
| multilingual-e5-small | search for norms and FAS cases | used as is |
| Qwen2.5-7B-Instruct Q4 | explanations, fallback fixes | used as is |
| finding filter (TF-IDF + logistic regression) | learns from expert feedback | yes, automatically |

RuBERT is trained on *weak* labels produced by rules: accuracy 0.68 / macro-F1 0.72 against those labels. It's a helper signal, not the main detector.

**9. How does it learn, and what protects it from bad feedback?**
- Votes, category corrections, "missed" reports and edits are stored in SQLite and exported as JSONL.
- The filter is retrained in the background: every 30 minutes, if there are at least 10 new verdicts.
- A new version is switched on only if, on the control documents, it keeps everything found before, adds no false errors, and downgrades nothing.

In a test with deliberately harmful feedback (rejecting real contradictions), the gate rejected the new version.

**10. Where is the data from? Is it legal?**
All public:
- ЕИС: 321 procurements, 46,752 clauses;
- FAS decisions: 437 cases, 420 complaint arguments;
- law texts from КонсультантПлюс, Гарант and RusLawOD;
- ОКПД2: 21,081 codes.

Laws are public domain; RusLawOD is CC BY-NC (non-commercial). Collected once; reviewing a document makes no network calls.

**11. Isn't this tuned to the two example documents?**
The checks are general rules: units, ОКПД2 against the classifier, warranty basis by contract type, brand without "или эквивалент". They aren't string matches on the samples. We also wrote two ТЗ from other areas (cleaning services, IT hardware) to check that the logic works beyond lifts and metrology. An independent test on real labelled FAS complaints is the next step.

**12. Precision/recall on real documents?**
Not measured: there are no expert labels for real ЕИС documents yet. We won't claim a number we don't have.

### About practicality

**13. Speed and deployment?**
- 1–3 s per document without the LLM.
- `./setup.sh` plus `docker compose up`.
- Lite mode fits in under 1 GB RAM.
- Login via Yandex ID or Google, and access can be restricted to a domain.

**14. Formats?**
DOCX, DOC, RTF, ODT, text PDF and XLSX. Scanned PDFs aren't supported (no OCR).

**15. Output?**
- the corrected DOCX;
- a DOCX with highlights and Word comments;
- a conclusion as DOCX/HTML;
- JSON.

**16. 44-ФЗ?**
The base already has 44-ФЗ by part, and most checks don't depend on which law applies. It hasn't been tested on 44-ФЗ documents.

**17. Next steps?**
1. Label real FAS complaints to build an independent test set.
2. A check for "valid but not the best" ОКПД2 codes.
3. Customers' procurement regulations from ЕИС.
4. LoRA fine-tuning of the LLM on stored expert edits.

**18. Who did what?**
*Prepare your own answer:* who built data collection, the checks, the UI and the deploy.

### Phrases to avoid
- Any "N out of N" or percentage; "finds all errors", "0 false positives", "AI detects violations", "runs on MIPT's server".
- Say instead: a concrete example ("на ТЗ лифта система показывает…"), "правила находят, база обосновывает, LLM поясняет", "разворачивается на своём сервере".
- If you don't know: «Это мы не измеряли — вот как бы мы это проверили…»
