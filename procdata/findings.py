"""Extract per-argument findings from FAS decision texts into fas_findings.

Everything here is regex over the decision's own wording. The challenged requirement is recorded only when the
decision quotes it («...»); otherwise challenged_text stays NULL and challenged_text_missing=1 so it can be
pulled from the original procurement documentation later. Rows are 'unreviewed' until a human checks them.
"""
import json, re
from .common import log, upsert

WS = re.compile(r"[ \t\xa0]+")
LAW_ALIAS = {"закона о закупках": "223-ФЗ", "закон о закупках": "223-ФЗ", "223-фз": "223-ФЗ",
             "закона о контрактной системе": "44-ФЗ", "44-фз": "44-ФЗ",
             "закона о защите конкуренции": "135-ФЗ", "135-фз": "135-ФЗ"}
PROV = re.compile(r"(?:пункт\w*\s*(\d+(?:\.\d+)*)\s+)?(?:част\w*\s*(\d+(?:\.\d+)*)\s+)?стать\w*\s*(\d+(?:[.\-]\d+)*)"
                  r"\s+(?:Федерального\s+)?(Закона о закупках|Закона о контрактной системе|Закона о защите конкуренции"
                  r"|закона\s*(?:от\s+[\d.]+\s*(?:г\.)?\s*)?№?\s*(?:223|44|135)-ФЗ|(?:№\s*)?(?:223|44|135)-ФЗ)", re.I)
VIOL = re.compile(r"(?:нарушени\w+|нарушивш\w+|нарушил\w*)\s+(?:требовани\w+\s+)?((?:(?:пункт|част|стать)\w*\s*[\d.\-]+[,\s]*(?:и\s+)?)+\s*(?:Федерального\s+)?(?:Закона о закупках|Закона о контрактной системе|закона\s*(?:от\s+[\d.]+\s*(?:г\.)?\s*)?№?\s*(?:223|44)-ФЗ|№?\s*(?:223|44)-ФЗ))", re.I)
ARG_SPLIT = re.compile(r"(?:^|\n)\s*(\d{1,2})[.)]\s+(?=[А-ЯЁ«\"])")
ARG_VERDICT = re.compile(r"довод\w*(?:\s+\w+){0,12}?\s+(?:признан\w*|признаётся|признается|является|являются)\s+(не\s*обоснованн\w*|обоснованн\w*|несостоятельн\w*)", re.I)
QUOTE = re.compile(r"«([^»]{40,600})»")
LAW_TITLE = re.compile(r"^(О |Об |О внесении|Положени[ея] о закупк|Закон)", re.I)
CUSTOMER = re.compile(r"((?:Представител\w+\s+)?Заказчик\w*\s+(?:пояснил|указал|сообщил|представил|считает|полагает|возраж|не согласил|затруднился|просил)[^\n]{0,700})", re.I)
REASON = re.compile(r"((?:Комиссия|Комиссией)[^\n]{0,40}?(?:приходит к выводу|пришла к выводу|установила|признает|признаёт|считает|отмечает)[^\n]{0,900})", re.I)
TYPE_HINTS = [("TECHNICAL", r"техническ\w+ (задани|характеристик|требовани)|характеристик\w+ товара|описани\w+ предмета|ГОСТ|эквивалент|товарн\w+ знак"
                            r"|прибор|оборудовани|средств\w* измерен|поверк|параметр|производител|комплектац|мощност|габарит|не менее \d|не более \d|модел\w* "),
              ("QUALIFICATION", r"требовани\w+ к участник|опыт\w*|квалификац|лиценз|членств|СРО"),
              ("EVALUATION", r"критери\w+ оценк|порядк\w* оценк|сопоставлени"),
              ("DOCUMENTATION", r"состав\w* заявк|документ\w+ в составе|форм\w+ заявк|не установил\w* в документации|положени\w+ о закупке"),
              ("PROCEDURE", r"отклонил|отклонени|срок\w* подачи|протокол|разъяснени|извещени|электронн\w+ форм")]


def _norm_law(raw):
    r = raw.lower()
    for k, v in LAW_ALIAS.items():
        if k in r: return v
    m = re.search(r"(223|44|135)-фз", r)
    return f"{m.group(1)}-ФЗ" if m else raw


def provisions(text):
    out = []
    for point, part, art, law in PROV.findall(text):
        s = f"{_norm_law(law)} ст.{art}" + (f" ч.{part}" if part else "") + (f" п.{point}" if point else "")
        if s not in out: out.append(s)
    return out


def violated(text):
    out = []
    for chunk in VIOL.findall(text):
        law = _norm_law(chunk)
        # expand "пункт 2 части 1 статьи 3" and lists like "часть 1, 6 статьи 3"
        arts = re.findall(r"стать\w*\s*([\d.\-]+)", chunk)
        parts = re.findall(r"част\w*\s*([\d.,\s]+?)(?=\s*(?:стать|пункт|и\b|$))", chunk)
        points = re.findall(r"пункт\w*\s*([\d.,\s]+?)(?=\s*(?:част|стать|и\b|$))", chunk)
        for a in arts or [None]:
            base = f"{law} ст.{a}" if a else law
            plist = [p.strip() for pp in parts for p in pp.split(",") if p.strip()] or [None]
            for p in plist:
                s = base + (f" ч.{p}" if p else "")
                for pt in [q.strip() for qq in points for q in qq.split(",") if q.strip()] or [None]:
                    s2 = s + (f" п.{pt}" if pt else "")
                    if s2 not in out: out.append(s2)
    return out


def req_type(text):
    t = text.lower()
    for name, pat in TYPE_HINTS:
        if re.search(pat, t): return name
    return "OTHER"


def _section(text):
    a = text.find("УСТАНОВИЛА"); b = text.rfind("РЕШИЛА")
    if a < 0: a = 0
    if b < 0 or b <= a: b = len(text)
    return text[a:b], text[b:]


def _arguments(body):
    """Numbered доводы after 'Согласно доводам жалобы' / 'в частности:'; fallback = whole complaint paragraph."""
    k = re.search(r"(довод\w* жалобы|заявитель (?:считает|полагает|указывает|обжалует)|в частности:)", body, re.I)
    start = k.start() if k else 0
    window = body[start:start + 6000]
    pieces = ARG_SPLIT.split(window)
    args = []
    if len(pieces) >= 3:
        for i in range(1, len(pieces) - 1, 2):
            txt = pieces[i + 1].strip()
            txt = re.split(r"\n(?=Жалоба рассмотрена|Комиссия|Выслушав|Изучив|В соответствии|Согласно|Представитель)", txt)[0]
            if len(txt) > 25: args.append(txt[:1500])
    if not args:
        m = re.search(r"(?:Согласно доводам жалобы|По мнению Заявителя|Заявитель (?:считает|полагает|указывает))[,:]?\s*([^\n]{20,1500})", body, re.I)
        if m: args.append(m.group(1))
    return args


def extract_all(db, limit=None):
    rows = db.execute("SELECT d.doc_uuid, d.case_id, d.eis_id_mentioned, d.outcome, d.full_text FROM fas_documents d "
                      "WHERE (d.doc_kind LIKE 'Решение%' OR d.title LIKE '%РЕШЕНИЕ%') AND length(d.full_text) > 1500"
                      + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    n_rows = 0
    for r in rows:
        text = WS.sub(" ", r["full_text"])
        body, operative = _section(text)
        viol = violated(body + " " + operative)
        prov = provisions(body)
        cust = [m.group(1).strip() for m in CUSTOMER.finditer(body)]
        reasons = [m.group(1).strip() for m in REASON.finditer(body)]
        verdicts = [(m.start(), m.group(1).lower()) for m in ARG_VERDICT.finditer(body)]
        args = _arguments(body)
        quotes = [q for q in QUOTE.findall(body) if re.search(r"требован|должн|не менее|не более|наличие|соответств", q, re.I) and not LAW_TITLE.match(q)]
        doc_outcome = r["outcome"]
        if not args:
            args = [None]
        for i, arg in enumerate(args, 1):
            # per-argument verdict: i-th "довод ... признается ..." if the counts line up, else the document outcome
            if len(verdicts) == len(args):
                v = verdicts[i - 1][1]
                oc = "DISMISSED" if ("не" in v and "обоснован" in v) or "несостоятельн" in v else "UPHELD"
            elif doc_outcome in ("UPHELD", "DISMISSED"):
                oc = doc_outcome
            else:
                oc = "UNKNOWN"
            quote = None
            if arg:
                qs = [q for q in QUOTE.findall(arg) if not LAW_TITLE.match(q)]
                quote = next((q for q in qs if len(q) >= 40), None)
            if quote is None and len(args) == 1 and quotes:
                quote = quotes[0]
            upsert(db, "fas_findings", {
                "finding_id": f"{r['doc_uuid']}:{i}", "case_id": r["case_id"], "doc_uuid": r["doc_uuid"],
                "procurement_notice_id": r["eis_id_mentioned"], "argument_no": i,
                "challenged_text": quote, "challenged_text_missing": 0 if quote else 1,
                "requirement_type": req_type(arg or body[:3000]),
                "complainant_argument": arg, "customer_argument": "\n".join(cust[:3]) or None,
                "fas_reasoning": "\n".join(reasons[:4]) or None,
                "legal_provision": json.dumps({"violated": viol, "cited": prov[:15]}, ensure_ascii=False),
                "outcome": oc, "violation_established": {"UPHELD": "yes", "DISMISSED": "no"}.get(oc, "unknown"),
                "extraction_method": "regex", "review_status": "unreviewed"}, "finding_id")
            n_rows += 1
    db.commit()
    log.info("fas_findings: %d rows from %d decisions", n_rows, len(rows))
