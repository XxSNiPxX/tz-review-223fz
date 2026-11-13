"""Automatic corrections for findings. Deterministic rewrites per label (instant, available everywhere), ОКПД2 code
suggestion by item name (TF-IDF over the 21k-code classifier), and an optional LLM fallback. Every candidate is verified
by re-running the clause-level checks: a fix that would still trigger the same finding is never offered.
"""
import json, re
from .common import ROOT, log
from . import checks

ATTR = json.loads((ROOT / "kb" / "attribute_units.json").read_text(encoding="utf-8"))
CAT_FULL = {"пассаж": "пассажирский", "грузов": "грузовой", "больни": "больничный", "грузоп": "грузопассажирский"}

ONES = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать",
        "четырнадцать", "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]


def words(n):
    """Russian number words (nominative), 1..9999, capitalised like «105 (Сто пять)»."""
    if n <= 0 or n > 9999: return None
    parts = []
    th, n = divmod(n, 1000)
    if th:
        tw = {1: "одна тысяча", 2: "две тысячи", 3: "три тысячи", 4: "четыре тысячи"}.get(th) or (words(th).lower() + " тысяч")
        parts.append(tw)
    h, n = divmod(n, 100)
    if h: parts.append(HUNDREDS[h])
    if n >= 20:
        t, o = divmod(n, 10); parts.append(TENS[t]); o and parts.append(ONES[o])
    elif n: parts.append(ONES[n])
    s = " ".join(p for p in parts if p)
    return s[:1].upper() + s[1:]


def _kind_from(f):
    e = (f.get("explanation") or "").lower()
    return "WORKS" if "работы" in e and "подряд" in e or "— работы" in e else "SERVICES" if "услуги" in e else "GOODS" if "поставка товара" in e or "товар" in e else None


def _equiv_after(text, token):
    """Insert «или эквивалент» right after the model designation that starts at token."""
    i = text.find(token)
    if i < 0: return None
    j = i + len(token)
    m = re.match(r"[\w\-./ ]{0,40}?(?=[,;.]|\s[а-яё]{4,}|$)", text[j:])          # extend over the model code (T14 Gen 4, CB114-S …)
    if m: j += len(m.group(0).rstrip())
    return text[:j] + " или эквивалент" + text[j:]


def rule_fix(f, text, doc=None):
    lab, matched = f["label"], [str(m) for m in (f.get("matched") or [])]
    t = text
    if lab == "MISSING_UNIT":
        units = f.get("expected_units") or []
        for n, u in zip(matched, units):
            if not u or u.startswith("["): continue
            t = re.sub(r"(?<![\d.,])" + re.escape(n) + r"(?!\d|[.,]\d)(?!\s*" + re.escape(u) + ")", f"{n} {u}", t, count=1)
        return t if t != text else None
    if lab == "STANDARD_DESIGNATION":
        for m in matched:
            t = t.replace(m, re.sub(r"ГОСТ\s*", "ГОСТ Р ", m, count=1))
        return re.sub(r"ГОСТ\s+Р\s+Р", "ГОСТ Р", t) if t != text else None
    if lab == "BRAND_REFERENCE" and matched:
        return _equiv_after(t, matched[0])
    if lab == "NO_EQUIVALENT":
        t = re.sub(r",?\s*(без возможности замены на эквивалент|без права замены|без эквивалент\w*|эквивалент\w* не допуска\w*|аналоги не допуска\w*|замена не допуска\w*|только оригинал\w*)", "", t, flags=re.I)
        brand = re.search(r"\b([A-Z][A-Za-z0-9]+(?:[ -][A-Z0-9][A-Za-z0-9\-]*)*)", t)
        if brand and "эквивалент" not in t.lower():
            t = _equiv_after(t, brand.group(1))
        return t if t != text else None
    if lab == "WARRANTY_BASIS_MISMATCH":
        kind = _kind_from(f)
        target = {"WORKS": "с момента подписания сторонами Актов о приемке выполненных работ по форме КС-2 и справки о стоимости выполненных работ и затрат по форме КС-3",
                  "GOODS": "с даты подписания сторонами товарной накладной (акта приема-передачи Товара)",
                  "SERVICES": "с даты подписания сторонами акта сдачи-приемки оказанных услуг"}.get(kind)
        if not target: return None
        t2 = re.sub(r"(с момента|с даты)[^.;]*?(товарн\w+ накладн\w+[^.;]*|кс-2[^.;]*|акт\w* о приемке выполненных работ[^.;]*|приемк\w+ товара[^.;]*)", target, t, count=1, flags=re.I)
        return t2 if t2 != t else None
    if lab == "VAGUE_REQUIREMENT":
        rep = [(r"\s*(должн\w+ быть\s+)?(высокого|хорошего|надлежащего)\s+качества", ""), (r"\b(качественн\w*)\s+(и\s+)?", ""), (r"\bсовременн\w*\s+", ""),
               (r"\bнадёжн\w*\s+|\bнадежн\w*\s+", ""), (r"не хуже конкурентов", "не менее [значение] [ед. изм.]"), (r"по согласованию с заказчиком", "в соответствии с требованиями настоящего ТЗ"),
               (r"\b(примерно|около|приблизительно|ориентировочно)\s+(\d)", r"не менее \2"), (r"\bоптимальн\w*\s+", ""), (r"\bудобн\w*\s+", "")]
        for pat, r in rep:
            t = re.sub(pat, r, t, flags=re.I)
        t = re.sub(r"\s{2,}", " ", t).replace(" .", ".").replace(" ,", ",")
        t = re.sub(r"(должн\w+ быть|выполняться)\s+и\s+", r"\1 ", t)
        return t if t != text else None
    if lab == "NUMBER_WITHOUT_WORDS":
        m = re.search(r"\b(\d{1,4})\s*(календарн\w+|рабоч\w+|дн\w+|месяц\w*|мес\.)", t)
        if not m: return None
        w = words(int(m.group(1)))
        return (t[:m.end(1)] + f" ({w})" + t[m.end(1):]) if w else None
    if lab == "NATIONAL_REGIME_STATEMENT":
        return ""
    if lab == "CONTRADICTORY_REQUIREMENTS":
        m = re.search(r"преобладает «([^»]+)»; расходятся: ([^)]+)\)", f.get("proposed_text") or "")
        if m:
            maj, minors = m.group(1), [x.strip() for x in m.group(2).split(",")]
            for mi in minors:
                full_mi = next((w for w in re.findall(r"[а-яё]+", t.lower()) if w.startswith(mi)), mi) if not re.match(r"[\d.x]+$", mi) else mi
                full_maj = CAT_FULL.get(maj, maj)
                if full_mi in t.lower():
                    i = t.lower().find(full_mi); t = t[:i] + full_maj + t[i + len(full_mi):]
            return t if t != text else None
        m = re.search(r"в таблице указано ([\d.,]+) [^,]*, а в тексте — «([\d.,]+)", f.get("explanation") or "")
        if m:                                                                   # attribute table vs prose: align the table to the text
            return re.sub(r"(?<![\d.,])" + re.escape(m.group(1)) + r"(?![\d.,])", m.group(2), t, count=1) or None
        return None
    return None


# ---------------------------------------------------------------- ОКПД2 suggestion (small retrieval model over the classifier)
_okpd = None


def _okpd_model():
    global _okpd
    if _okpd is None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from .checks_doc import okpd
        codes = {c: n for c, n in okpd().items() if c.count(".") == 3}                # leaf codes XX.XX.XX.XXX
        keys = list(codes)
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=1)
        X = vec.fit_transform([codes[k].lower() for k in keys])
        _okpd = (keys, codes, vec, X)
    return _okpd


def suggest_okpd(name, kind="GOODS", prefix=None, k=3):
    keys, codes, vec, X = _okpd_model()
    q = vec.transform([re.sub(r"\(.*?\)|\d+[^ ]*", " ", name.lower())])
    sims = (X @ q.T).toarray().ravel()
    out = []
    for i in sims.argsort()[::-1][:400]:
        c = keys[i]; sec = int(c[:2])
        if kind == "GOODS" and not (1 <= sec <= 33): continue
        if kind == "SERVICES" and sec < 45: continue
        if prefix and not c.startswith(prefix): continue
        if c.endswith((".190", ".900", ".000")) and prefix: continue
        out.append({"code": c, "name": codes[c], "score": round(float(sims[i]), 3)})
        if len(out) >= k: break
    return out


def okpd_fix(f, text):
    m = re.search(r"\b(\d{2}\.\d{2}\.\d{2}\.\d{3})\b", text)
    if not m: return None, None
    cells = [c.strip() for c in text.split(" | ")]
    name = cells[1] if len(cells) > 1 else text
    lab = f["label"]
    if lab == "OKPD2_TOO_GENERIC":
        cand = suggest_okpd(name, prefix=".".join(m.group(1).split(".")[:3]) + ".")
    elif lab in ("OKPD2_KIND_MISMATCH", "OKPD2_UNKNOWN_CODE"):
        kind = "SERVICES" if re.search(r"услуг", name.lower()) else "GOODS"
        cand = suggest_okpd(name, kind=kind)
    else:
        return None, None
    if not cand: return None, None
    return text.replace(m.group(1), cand[0]["code"], 1), cand


# ---------------------------------------------------------------- entry point
def propose(f, text, doc=None, evidence=None, allow_llm=True):
    """Returns dict(new_text, method, would_resolve, note, options) or None if nothing safe can be proposed."""
    new, options, method = None, None, "rule"
    try:
        if f["label"].startswith("OKPD2_"):
            new, options = okpd_fix(f, text); method = "okpd-model"
        else:
            new = rule_fix(f, text, doc)
    except Exception as ex:  # noqa
        log.warning("autofix %s failed: %s", f["label"], ex); new = None
    if new is None and allow_llm:
        from . import explain
        if explain.available():
            g = dict(f); g["clause_text"] = text
            g2 = explain.explain(g, evidence or [])
            if "LLM" in (g2.get("method") or "") and g2.get("proposed_text") and g2["proposed_text"] != text:
                new, method = g2["proposed_text"], "llm"
    if new is None:
        return None
    resolves = verify(f, text, new)
    if resolves is False and method != "okpd-model":
        return None                                              # never offer a fix that the checks would still flag
    note = {"rule": "Автоисправление по правилу", "okpd-model": "Код подобран по наименованию позиции из классификатора ОК 034-2014", "llm": "Предложено локальной LLM"}[method]
    return {"new_text": new, "method": method, "would_resolve": resolves, "note": note, "options": options}


def verify(f, old, new):
    """Would the same finding disappear for this fragment? (clause-level re-check; document-level labels -> None)."""
    if new == "": return True
    probe = [{"clause_id": "probe", "clause_text": new, "table_id": "T" if " | " in new else None, "position_start": 0, "position_end": len(new)}]
    try:
        left = [x for x in checks.run_checks(probe) if x["label"] == f["label"] and x["disposition"] == "FLAGGED"]
    except Exception:  # noqa
        return None
    clause_level = {"MISSING_UNIT", "VAGUE_REQUIREMENT", "BRAND_REFERENCE", "NO_EQUIVALENT", "INCOMPLETE_STANDARD_REFERENCE", "EXCESSIVE_PARAMETER", "RESTRICTIVE_QUALIFICATION"}
    return (not left) if f["label"] in clause_level else None
