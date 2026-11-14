# Pitch (3 minutes) and judge Q&A

Deck: `docs/presentation.pdf`. Slides 1–7 are the pitch. Everything after "Запасные слайды" is backup, opened only when a question needs it.

**How the LLM is used (say it the same way every time):** the local LLM (Qwen2.5-7B) runs on every review. It explains findings and proposes fixes where the rules have none. Detection itself is done by the checks and the knowledge base, so the LLM never decides on its own. The only setup without the LLM is the small public demo server (709 MB RAM).

**Rule:** don't claim scores. The organisers' brief gives no number of problems and no metric, so any "N out of N" would be our own count and invites attack. Show concrete findings and the live demo instead.

## 3-minute script (≈ 30 s per slide)

| # | Time | Say (RU) | Meaning (EN) |
|---|---|---|---|
| 1 | 0:00–0:20 | «Мы сделали систему, которая находит проблемы в ТЗ на закупку по 223-ФЗ, объясняет их со ссылкой на закон и практику ФАС и исправляет. Всё работает на своём сервере: ноль внешних API, своя LLM, три модели мы обучили сами, а знания собрали из открытых данных — законы, решения ФАС, ЕИС, ОКПД2.» | What it is, plus the three highlights |
| 2 | 0:20–0:45 | «Облачный чат-бот получает документ заказчика, а ссылки на нормы берёт по памяти. У нас своя LLM работает локально и опирается на собранную базу, а саму проблему находят детерминированные проверки. В нашем тесте 7B-модель без базы переписала «не менее 7» в «ровно 7» — поэтому её ответ сверяется с базой.» | Why not ChatGPT |
| 3 | 0:45–1:20 | **Live demo from the laptop** (see below). Otherwise: «Документ пронумерован, проблемы подсвечены, у каждой — объяснение LLM. Ссылка ¶6 прокручивает к фрагменту. «Исправить» показывает было/станет, после подтверждения документ перепроверяется, правка попадает в раздел «Исправлено».» | What the user sees |
| 4 | 1:20–1:45 | «Около 30 проверок находят дефект, база даёт основание, LLM объясняет и предлагает правку. Если LLM ссылается на норму не из базы или добавляет числа — ответ отбрасывается. Нет данных — пишем «требует проверки».» | Architecture |
| 5 | 1:45–2:15 | «Модели: RuBERT мы дообучили на 46 тысячах пунктов реальных ТЗ, модель подбора ОКПД2 — по 21 тысяче кодов, и фильтр, который учится на оценках экспертов. Плюс открытые Qwen-7B и e5 — всё на CPU. Данные — 223-ФЗ и 44-ФЗ по частям, 420 доводов ФАС, 321 закупка из ЕИС, собраны своими сборщиками.» | Models and open data |
| 6 | 2:15–2:40 | «Пример — ТЗ организаторов на замену лифта: в таблице лифт пассажирский, в предмете — грузовой; 300 кг против 500; гарантия от товарной накладной вместо КС-2; лифт без позиции с кодом товара. Система учится на правках экспертов, но новая версия включается, только если не хуже прежней.» | Concrete example plus learning |
| 7 | 2:40–3:00 | «Всё открыто: три команды — и у вас свой экземпляр с моделями и базой, GPU не нужен. Дальше — оценка на размеченных жалобах ФАС и дообучение LLM на правках экспертов. Спасибо!» | Close |

**Live demo — run it from the laptop, not the public link.** The public server (709 MB RAM) runs without the LLM, so its cards have no LLM explanation. On the laptop (30 GB RAM, model present) the LLM runs on every review.
- **Before the pitch:** start the server (`uvicorn server:app --port 8000`) and open each sample document once. On CPU the LLM takes about a minute per explanation, so let it finish beforehand. Reopen from «Недавние проверки» during the demo.
- **Click path (40 s):** «Вычислительная техника» → finding 4 (Lenovo, no equivalent) → show the LLM explanation → «Исправить автоматически» → was/becomes → apply → «Исправлено».
- **Fallback:** if the laptop fails, use https://185-17-3-218.sslip.io (works without the LLM) or slide 3.

## Numbers you may say (all verifiable)

| Claim | Basis |
|---|---|
| 0 external APIs | reviewing a document makes no network calls; the LLM runs on our own machine |
| 3 + 2 models | trained by us: RuBERT-tiny2 clause-role classifier, ОКПД2 matcher, feedback filter. Open, used as is: Qwen2.5-7B, multilingual-e5-small |
| 4 open data sources | laws (КонсультантПлюс, Гарант, RusLawOD), FAS decisions, ЕИС, ОКПД2 |
| 420 FAS arguments, 21,081 ОКПД2 codes, 46,752 ЕИС clauses, 1,623 law norms | size of the collected knowledge base |
| ~1 min per LLM explanation | on CPU; explanations appear one by one after the checks |
| ≥ 10 GB RAM | needed for the LLM; the 709 MB demo server runs without it |

**Don't volunteer scores.** If asked "how did you evaluate?", see question 3.

## Likely questions and answers

### About the solution

**1. Why not just use an LLM (GigaChat / YandexGPT / ChatGPT)?**
Three reasons:
- customer documents shouldn't leave the organisation;
- an LLM's legal references come from memory and must be re-checked, and in our test it changed "не менее 7" into "ровно 7";
- the result isn't reproducible.

So we run our own LLM locally. The checks and the knowledge base decide whether something is a problem; the LLM explains it and proposes fixes. An LLM answer that cites a norm outside our base, or adds numbers that aren't in the text, is discarded.

**2. What exactly does the LLM do?**
Qwen2.5-7B-Instruct (4-bit, llama.cpp, CPU) runs on every review:
- it writes the explanation for findings where wording matters (contradictions, brand / no equivalent, excessive or vague requirements, restrictive qualification, standards);
- it proposes a fix when no rewrite rule fits.

It needs about 10 GB RAM and takes about a minute per explanation on CPU, so explanations appear a little after the rule results. The small public demo server (709 MB RAM) can't hold it and runs without it. Detection doesn't change there, only the explanation text.

**2a. Why not fine-tune the LLM?**
Every expert edit is already stored as a "before → after" pair. Once there are enough of them, LoRA fine-tuning is the next step. Until then, grounding the LLM in the knowledge base is safer than training on little data.

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
| ОКПД2 matcher (character TF-IDF over the classifier) | picks the code by item name | yes, built from all 21,081 codes |
| finding filter (TF-IDF + logistic regression) | learns from expert feedback | yes, retrained automatically |
| Qwen2.5-7B-Instruct Q4 | explanations, fixes where rules have none | open, used as is |
| multilingual-e5-small | search for norms and FAS cases | open, used as is |

If asked "is the ОКПД2 matcher really a model?": it's a retrieval model fitted on the classifier text. It isn't a neural network, and you should say so.

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
- The checks take a few seconds; each LLM explanation takes about a minute on CPU.
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
- Any "N out of N" or percentage; "finds all errors", "0 false positives", "the LLM finds violations", "runs on MIPT's server"; showing the LLM on the public link (it has none).
- Say instead: a concrete example ("на ТЗ лифта система показывает…"), "правила находят, база обосновывает, LLM поясняет", "разворачивается на своём сервере".
- If you don't know: «Это мы не измеряли — вот как бы мы это проверили…»
