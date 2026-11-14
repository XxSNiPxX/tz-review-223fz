# Pitch (3 minutes) and judge Q&A

Deck: `docs/presentation.pdf`. Slides 1–6 are the pitch. Everything after "Запасные слайды" is backup, opened only when a question needs it.

**Rule for every number:** say exactly what was measured, and don't round it up. Every figure below comes from `eval_case.py` / `eval_autofix.py` and can be shown live.

## 3-minute script (≈ 30 s per slide)

| # | Time | Say (RU) | Meaning (EN) |
|---|---|---|---|
| 1 | 0:00–0:20 | «Мы сделали систему, которая подсвечивает проблемы в ТЗ на закупку по 223-ФЗ, показывает основание и предлагает исправление. Работает на своём сервере, без внешних API. На документах организаторов система отметила все 10 правок эксперта: 4 — как ошибку, 6 — как "требует проверки".» | What it is; the headline number with its breakdown |
| 2 | 0:20–0:50 | «Облачный чат-бот получает документ заказчика, а ссылки на нормы берёт по памяти — их надо перепроверять. У нас основания берутся из собранной базы: 223-ФЗ по частям, доводы из решений ФАС, ОКПД2. Проверки детерминированные, а LLM только поясняет: в нашем тесте 7B-модель без базы переписала "не менее 7" в "ровно 7".» | Why not a chatbot |
| 3 | 0:50–1:30 | **Live demo if possible** (see below). Otherwise: «Документ пронумерован, проблемы подсвечены. Ссылка ¶6 прокручивает к фрагменту. "Исправить" показывает было/станет, после подтверждения документ перепроверяется, правка попадает в раздел "Исправлено".» | What the user sees |
| 4 | 1:30–2:00 | «Около 30 проверок, база знаний и модели: RuBERT — роль пункта, e5 — поиск норм и решений ФАС, Qwen-7B — пояснения. Если данных не хватает, система пишет "требует проверки", а не "нарушение".» | Architecture |
| 5 | 2:00–2:35 | «Честно о результатах. Лифт: 6 из 6 отмечены, 4 как ошибка. Метрология: 4 из 4, все — "требует проверки". Два пункта покрыты частично: один код работ и 2 из 5 кодов ОКПД2 мы не замечаем. На исправленных экспертом версиях нет подтверждённых ошибок. Два своих ТЗ из других областей мы сделали как контроль переобучения. Система учится на правках экспертов, но новая версия включается, только если на эталонах она не хуже.» | Results, honest |
| 6 | 2:35–3:00 | «Всё открыто: три команды — и у вас свой экземпляр; демо работает на сервере с 709 МБ памяти. Эталон пока маленький, следующий шаг — разметка реальных жалоб ФАС. Попробуйте: демо-вход, пример, "Исправить автоматически". Спасибо!» | Close, plus the limitation and next step |

**Live demo (40 s, rehearse it):** https://185-17-3-218.sslip.io → «Войти в демо-режиме» → sample «Вычислительная техника» → finding 4 (Lenovo, no equivalent) → «Исправить автоматически» → was/becomes → apply → «Исправлено». Keep slide 3 open as a fallback in case the network fails.

## Exact numbers (know them by heart)

| Claim | Exact meaning |
|---|---|
| 10/10 | 10 required expert corrections in the organisers' 2 documents. Each has a finding of the same category on that fragment: 4 confirmed as an error, 6 marked "требует проверки" |
| Lift 6/6 | confirmed errors: lift type, load capacity, warranty basis, missing goods line. "Требует проверки": door opening, ГОСТ without «Р» |
| Metrology 4/4 | all four marked "требует проверки": kits to split, ОКПД2 codes, missing characteristics, national-regime phrase |
| Partly covered | lift: the works code .120→.110 is not detected (only the missing goods line is). Metrology: 3 of 5 code problems found (two generic «…190» codes and one code missing from the classifier). Missed: штангенрейсмас .110→.122 and динамометр 26.51.62.120→26.51.66.111, which are valid codes, just not the best fit |
| 0 | no *confirmed* errors or risks on the expert-corrected versions. "Требует проверки" remarks remain: 3 (lift) and 15 (metrology) |
| 17/17 | our own two ТЗ (cleaning, IT hardware). We wrote them ourselves, so this is an overfitting check, not an independent score |
| 32 of 47 | on the 4 test documents, 32 of 47 findings got an automatic fix. All 32 passed our re-check with no new findings. Re-checked by our own rules, not by an expert |
| 1–3 s | one document, without the LLM |
| 709 MB | RAM of the demo server (lite mode, **no LLM**) |

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

**3. "10/10", but 6 of them are only "требует проверки". Isn't that cheating?**
"Требует проверки" means the system found the spot and the problem type but doesn't have enough data to state a violation (e.g. it can't be sure a kit's contents are missing rather than described elsewhere). For a procurement specialist, a highlighted spot with an explanation is the useful part. We show the split openly: 4 confirmed, 6 to check.

**4. What do you miss?**
- The lift's wrong works code (.120 instead of .110).
- In metrology, 2 of 5 code corrections where the code exists but isn't the best one. We only detect codes that are too generic or don't exist. A "valid but better code exists" check is next.
- Customers' own procurement regulations and the SME list are not in the base yet.

**5. "0 false errors" — but the corrected metrology document still shows 15 remarks?**
Yes. The "0" counts only *confirmed* errors and risks. The 15 remarks are "требует проверки": generic «…190» codes the expert left in place, numbers without units, standards without a year. Arguably some of them are real.

**6. How does it understand context, e.g. "4 остановки" needs no unit?**
An attribute dictionary classifies each characteristic as a count, dimensionless, or a physical quantity. Only physical quantities without a unit are flagged, and the expected unit is suggested.

**7. How does the auto-fix work, and can it break something?**
- There is a rewrite rule per problem type. ОКПД2 codes are picked by item name from 21,081 codes. The LLM is a fallback.
- Before a fix is offered, the checks are re-run on the new text. If the problem would remain, the fix isn't offered.
- After the user confirms, the whole document is re-checked.

On the test set, 32 of 47 findings got a fix and all 32 passed the re-check. That re-check uses our own rules; an expert didn't grade the wording. Kits and contents aren't fixed automatically.

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
- A new version is switched on only if, on the gold set, it keeps all required findings, adds no false errors, and downgrades nothing.

In a test with deliberately harmful feedback, the candidate would have kept only 17 of 27 findings, and the gate rejected it.

**10. Where is the data from? Is it legal?**
All public:
- ЕИС: 321 procurements, 46,752 clauses;
- FAS decisions: 437 cases, 420 complaint arguments;
- law texts from КонсультантПлюс, Гарант and RusLawOD;
- ОКПД2: 21,081 codes.

Laws are public domain; RusLawOD is CC BY-NC (non-commercial). Collected once; reviewing a document makes no network calls.

### About the evaluation

**11. Two documents is a tiny test set.**
Agreed. That's why:
- we report the organisers' documents separately;
- our own two ТЗ are labelled as an overfitting check, not a score;
- the next step is labelling real FAS complaints so we can measure on documents we didn't write.

The feedback loop also produces labelled data as experts use it.

**12. Precision/recall on real documents?**
Not measured: we have no expert labels for real ЕИС documents yet. We won't claim a number we don't have.

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
- "finds all errors", "0 false positives", "AI detects violations", "runs on MIPT's server"
- Say instead: "отметила 10 из 10 (4 ошибкой, 6 "требует проверки")", "0 подтверждённых ошибок на исправленных версиях", "правила находят, база обосновывает, LLM поясняет", "разворачивается на своём сервере"
- If you don't know: «Это мы не измеряли — вот как бы мы это проверили…»
