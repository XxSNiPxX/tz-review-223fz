"""Tier 1: deterministic checks over the clauses of one procurement / one uploaded ТЗ.

Every check returns findings in the common schema (see docs/architecture.md §4) with evidence that resolves to
knowledge-base objects: a legal rule_id, a lexicon entry, or another clause. No model, no network.
"""
import json, re, uuid
from collections import defaultdict
from pathlib import Path
from .common import ROOT

LEX = json.loads((ROOT / "kb" / "lexicon.json").read_text(encoding="utf-8"))
NUM = r"\d+(?:[.,]\d+)?"
UNIT_ALT = "|".join(sorted((re.escape(u) for u in LEX["units"]), key=len, reverse=True))
NUM_WITH_UNIT = re.compile(rf"({NUM})\s*({UNIT_ALT})(?![а-яa-z])", re.I)
NUM_ANY = re.compile(rf"(?<![\d.,№/\-а-яА-Яa-zA-Z])({NUM})(?![\d%°/\-а-яА-Яa-zA-Z]|[.,]\d)")
RANGE_WORDS = re.compile(r"не (менее|более|ниже|выше|ранее|позднее)|от\s+\d|до\s+\d|в пределах|диапазон", re.I)
CAP_BRAND = re.compile(r"\b([A-Z][A-Za-z0-9]{2,}(?:[ -][A-Z][A-Za-z0-9]+)*)\b")
GOST = re.compile(LEX["gost_pattern"]); GOST_BAD = re.compile(LEX["gost_incomplete_pattern"])

# rule ids used by the compliance-flavoured checks (exist in legal_rules from consultant.ru text)
R_EQUIV = "223ФЗ_ART3_P6.1"     # description of the subject; trademarks require "или эквивалент" unless exception
R_EQUAL = "223ФЗ_ART3_P6"       # requirements apply equally; nothing outside the documentation
R_PRINC = "223ФЗ_ART3_P1"       # principles: no unjustified restriction of competition
R_DOC = "223ФЗ_ART4_P10"        # mandatory content of the documentation


def _f(clause, analysis, label, severity, explanation, evidence, proposed=None, confidence=0.9, method="RULE", disposition="FLAGGED", matched=None):
    return {"matched": matched or [],"finding_id": "F_" + uuid.uuid4().hex[:10], "clause_id": clause.get("clause_id"), "procurement_id": clause.get("procurement_id"),
            "span_start": clause.get("position_start"), "span_end": clause.get("position_end"), "page": clause.get("page_number"),
            "analysis_type": analysis, "label": label, "severity": severity, "disposition": disposition,
            "evidence": evidence, "explanation": explanation, "proposed_text": proposed, "confidence": confidence,
            "method": method, "clause_text": clause.get("clause_text", "")[:600]}


def _is_whitelisted(text):
    t = text.lower()
    return any(w in t for w in LEX["standard_223_provisions_whitelist"])


MONTHS = r"(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)"
DATE_LIKE = re.compile(rf"\b\d{{1,2}}[./]\d{{1,2}}[./]\d{{2,4}}|\b\d{{1,2}}\s+{MONTHS}|(?:№|\bN)\s*[\w\-/]*\d|\d+-ФЗ|\d+-п\b|\d+-р\b|\d{{4}}\s*г\.", re.I)
TABLE_CELL = re.compile(r"(?:^|\|)\s*\d+(?:[.,]\d+)?\s*(?=\||$)", re.M)


def clause_scope(clause):
    """TECHNICAL (run all checks) | CONTRACT (skip completeness/competition) | LEGAL (citations/boilerplate, skip)."""
    tl = clause["clause_text"].lower()
    fn = (clause.get("document_name") or "").lower()
    if any(k in fn for k in ("договор", "контракт")): return "CONTRACT"
    if sum(c in tl for c in LEX["contract_boilerplate_cues"]) >= 2: return "CONTRACT"
    if sum(c in tl for c in LEX["legal_citation_cues"]) >= 2 and not any(c in tl for c in LEX["numeric_attribute_cues"][:20]): return "LEGAL"
    return "TECHNICAL"


# ------------------------------------------------------------------ completeness
def check_missing_units(clause):
    t = clause["clause_text"]
    tl = t.lower()
    if not any(c in tl for c in LEX["numeric_attribute_cues"]): return []
    if GOST.search(t): t = GOST.sub(" ", t)
    t = DATE_LIKE.sub(" ", t)          # dates, document numbers, law numbers are not measurements
    t = re.sub(r"(\d)\s*\([а-яё\s\-]{3,60}\)", r"\1", t, flags=re.I)   # "12 (двенадцати) месяцев" -> "12 месяцев"
    # "размеры, мм (ШхГхВ) не менее 820х560х1800": unit given once before a dimension product
    t = re.sub(rf"((?:{UNIT_ALT})[^\d]{{0,60}}?)\d+(?:[.,]\d+)?(?:\s*[xх×*]\s*\d+(?:[.,]\d+)?){{1,2}}", r"\1 ", t, flags=re.I)
    t = TABLE_CELL.sub(" ", t)        # bare table cells (row numbers, quantities next to a unit cell)
    # "+20...+270 °C", "от 5 до 40 °C", "10-15 бар": the whole range shares the trailing unit
    t = re.sub(rf"[+\-]?\d+(?:[.,]\d+)?\s*(?:\.\.\.|…|-|–|до)\s*[+\-]?\d+(?:[.,]\d+)?\s*({UNIT_ALT})(?![а-яa-z])", " ", t, flags=re.I)
    with_unit = {m.group(1) for m in NUM_WITH_UNIT.finditer(t)}
    bare = [m.group(1) for m in NUM_ANY.finditer(t) if m.group(1) not in with_unit and not re.fullmatch(r"(19|20)\d{2}", m.group(1))
            and not re.match(r"\s*(?:\d+(?:\.\d+)*[.)]\s)", t[:m.end()+2])  # clause / item numbering at the start
            and not re.search(r"(п\.|пункт|раздел|глава|ст\.|статья|№|таблиц|приложени|лот)\s*$", t[max(0, m.start()-12):m.start()], re.I)]
    # only numbers that follow a measurable-attribute cue ("мощность ... 500"); counts like "10 уровней" are not measurements
    cue_re = re.compile(r"(" + "|".join(map(re.escape, LEX["numeric_attribute_cues"])) + r")\w*[^.;\n]{0,40}?(?<![\d.,])(" + NUM + r")(?![\d%°/-]|[.,]\d)", re.I)
    near = {m.group(2) for m in cue_re.finditer(t)}
    bare = [n for n in bare if n in near]
    if not bare: return []
    if re.search(r"класс(?:а|ом)?\s+точност|разряд|категори|класс защиты|степень защиты|ip\s*\d", tl):
        return []                                             # dimensionless class / grade numbers
    tight = re.compile(r"(" + "|".join(map(re.escape, LEX["numeric_attribute_cues"])) + r")\w*\s*(?:[:\-–—]|не менее|не более|до|от)?\s*(" + NUM + r")(?![\d%°/-]|[.,]\d)", re.I)
    confident = bool(tight.search(t)) and not with_unit
    return [_f(clause, "COMPLETENESS", "MISSING_UNIT", "ERROR" if confident else "RISK",
               f"Числовое значение ({', '.join(bare[:3])}) указано без единицы измерения при наличии измеримой характеристики." + ("" if confident else " Требует проверки: рядом есть другие значения с единицами."),
               [{"type": "lexicon", "id": "units"}], proposed="Указать единицу измерения для каждого числового значения (например, «не менее 16 ГБ»).",
               confidence=0.7 if confident else 0.45, disposition="FLAGGED" if confident else "INSUFFICIENT_EVIDENCE", matched=bare[:5])]


def check_vague(clause):
    tl = clause["clause_text"].lower()
    hits = [v for v in LEX["vague_terms"] if re.search(r"(?<![а-яё])" + re.escape(v) + r"(?![а-яё])", tl)]
    # stems catch Russian case endings ("качественной", "современным"); "качеств" alone is too broad, keep adjective stems only
    hits += [m.group(0) for v in LEX.get("vague_stems", []) for m in [re.search(r"(?<![а-яё])" + re.escape(v) + r"[а-яё]{0,4}(?![а-яё])", tl)] if m and m.group(0) not in hits
             and not re.search(re.escape(v) + r"[а-яё]{0,4}\s+(качеств|характеристик)", tl)]   # "высокого качества" handled by the phrase itself
    hits += [v for v in LEX.get("vague_terms_if_no_number", []) if re.search(re.escape(v) + r"(?!\s*[±+\-]?\s*\d)", tl) and v in tl]
    enum_hits = [v for v in LEX.get("enumeration_abbrev", []) if v in tl]
    out = []
    if enum_hits and not _is_whitelisted(tl) and (clause.get("table_id") or any(c in tl for c in LEX["numeric_attribute_cues"])):
        out.append(_f(clause, "COMPLETENESS", "OPEN_ENUMERATION", "NOTE",
                      f"Открытый перечень ({', '.join(enum_hits[:2])}) в требованиях к предмету закупки: участник не может определить полный состав требований.",
                      [{"type": "lexicon", "id": "enumeration_abbrev"}], proposed="Закрыть перечень или указать критерий отнесения.", confidence=0.35,
                      disposition="INSUFFICIENT_EVIDENCE", matched=enum_hits))
    if not hits or _is_whitelisted(tl): return out
    about_object = bool(clause.get("table_id")) or any(c in tl for c in LEX["numeric_attribute_cues"]) or re.search(r"товар|оборудован|издели|материал|характеристик|должен (?:быть|иметь|обеспечивать)", tl)
    procedural = re.search(r"согласовани\w+ с заказчиком|по согласованию", tl) and re.search(r"привлечени|субподряд|срок|график|порядок|допускается", tl)
    if procedural or not about_object:
        return out + [_f(clause, "COMPLETENESS", "VAGUE_REQUIREMENT", "NOTE",
                   f"Оценочная формулировка ({', '.join(hits[:3])}) в общих условиях; допустима, если не влияет на описание предмета закупки.",
                   [{"type": "lexicon", "id": "vague_terms"}], confidence=0.3, disposition="INSUFFICIENT_EVIDENCE", matched=hits)]
    return out + [_f(clause, "COMPLETENESS", "VAGUE_REQUIREMENT", "ERROR",
               f"Формулировка содержит неизмеримые или оценочные термины: {', '.join(hits[:3])}.",
               [{"type": "lexicon", "id": "vague_terms"}], proposed="Заменить оценочное требование на измеримое значение с единицей измерения и способом проверки.", confidence=0.75, matched=hits)]


def check_gost(clause):
    t = clause["clause_text"]
    if GOST_BAD.search(t) and not GOST.search(t):
        generic = re.search(r"действующ\w+ (ГОСТ|норматив)|ГОСТ\w*,\s*(СНиП|ТУ|СП)|и другим\w* (действующ\w+ )?норматив", t, re.I)
        return [_f(clause, "COMPLETENESS", "INCOMPLETE_STANDARD_REFERENCE", "NOTE" if generic else "ERROR",
                   "Общая отсылка к действующим ГОСТ/СНиП без конкретных обозначений: допустима как общее условие, но конкретные стандарты для предмета закупки должны быть перечислены отдельно." if generic else "Ссылка на ГОСТ без номера стандарта: требование невозможно проверить.",
                   [{"type": "lexicon", "id": "gost_pattern"}], proposed=None if generic else "Указать полное обозначение стандарта (например, ГОСТ Р 51318.22-2006).",
                   confidence=0.3 if generic else 0.8, disposition="INSUFFICIENT_EVIDENCE" if generic else "FLAGGED")]
    return []


def check_contradictions(clauses):
    """Same numeric attribute cue with different 'не менее/не более' bounds across clauses."""
    out, seen = [], defaultdict(list)
    for c in clauses:
        tl = c["clause_text"].lower()
        for cue in LEX["numeric_attribute_cues"]:
            if cue in ("количеств", "срок", "гаранти", "ресурс", "наработк") or cue not in tl: continue
            for m in re.finditer(rf"{cue}\w*[^.;\n]{{0,40}}?не (менее|более)\s*({NUM})\s*({UNIT_ALT})(?![а-яa-z])", tl):
                seen[(cue, m.group(1), m.group(3).lower())].append((c, m.group(2)))
    for (cue, kind, unit), items in seen.items():
        vals = {v for _, v in items}
        if len(vals) > 1:
            c0 = items[0][0]
            if len(items) > 6: continue        # same attribute across many catalogue items: a product list, not a contradiction
            out.append(_f(c0, "COMPLETENESS", "CONTRADICTORY_REQUIREMENTS", "RISK",
                          f"Характеристика «{cue}»: разные значения «не {kind}» в разных местах документа ({', '.join(sorted(vals))} {unit}).",
                          [{"type": "clause", "id": c["clause_id"]} for c, _ in items[:4]],
                          proposed="Оставить одно значение и удалить противоречащие упоминания.", confidence=0.6))
    return out


def check_sections(clauses, kind="goods"):
    text = " ".join(c["clause_text"].lower() for c in clauses)
    out = []
    checks = [("acceptance_cues", "MISSING_ACCEPTANCE_CRITERION", "Не найдены положения о порядке приемки / проверки соответствия."),
              ("delivery_cues", "MISSING_DELIVERY_DETAIL", "Не найдены место и срок поставки."),
              ("warranty_cues", "MISSING_WARRANTY_DETAIL", "Не найдены гарантийные требования."),
              ("quantity_cues", "MISSING_ATTRIBUTE", "Не найдено количество / объем поставки.")]
    anchor = clauses[0] if clauses else {"clause_text": ""}
    for key, label, msg in checks:
        if not any(cue in text for cue in LEX[key]):
            out.append(_f(anchor, "COMPLETENESS", label, "RISK", msg, [{"type": "lexicon", "id": key}, {"type": "rule", "id": R_DOC}],
                          proposed="Добавить соответствующий раздел в ТЗ или проект договора.", confidence=0.5))
    return out


# ------------------------------------------------------------------ competition / compliance
def check_brand(clause):
    t, tl = clause["clause_text"], clause["clause_text"].lower()
    if _is_whitelisted(tl): return []
    abbr = set(LEX["standards_abbreviations"])
    def _brandish(tok):
        head = re.split(r"[ -]", tok)[0]
        base = re.sub(r"\d+$", "", head).upper()
        if base in abbr or re.fullmatch(r"[A-Z]{1,4}\d*", head): return False   # IPX5, GN1, AISI, RS485 = standards
        return bool(re.search(r"[a-z]", head))                                     # Lenovo, ThinkPad, Intel
    brands = [b for b in CAP_BRAND.findall(t) if _brandish(b)]
    cue = any(c in tl for c in LEX["brand_cues"])
    if not brands and not cue: return []
    negated = any(m in tl for m in LEX["no_equivalent_markers"]) or re.search(r"(без|не допуска\w+|запрещ\w+|исключ\w+)[^.;\n]{0,40}эквивалент|эквивалент\w*[^.;\n]{0,20}(не допуска|не принима|не рассматрива|запрещ)", tl)
    if negated:
        return [_f(clause, "COMPETITION", "NO_EQUIVALENT", "RISK",
                   "Указание на конкретную марку/модель с прямым запретом эквивалента.",
                   [{"type": "rule", "id": R_EQUIV}, {"type": "rule", "id": R_PRINC}],
                   proposed="Удалить запрет эквивалента или обосновать его одним из исключений ч. 6.1 ст. 3 223-ФЗ (совместимость, запчасти, условия контракта).", confidence=0.85)]
    if brands and not any(m in tl for m in LEX["equivalent_markers"]):
        just = any(j in tl for j in LEX["compatibility_justifications"])
        return [_f(clause, "COMPETITION", "BRAND_REFERENCE", "RISK",
                   f"Упоминание товарного знака/модели ({', '.join(brands[:3])}) без слов «или эквивалент»" + (" ; в тексте есть ссылка на совместимость — обоснование требует проверки." if just else "."),
                   [{"type": "rule", "id": R_EQUIV}] + ([{"type": "lexicon", "id": "compatibility_justifications"}] if just else []),
                   proposed="Добавить «или эквивалент» и указать параметры эквивалентности, либо зафиксировать обоснование несовместимости.",
                   confidence=0.6 if just else 0.75, disposition="INSUFFICIENT_EVIDENCE" if just else "FLAGGED", matched=brands[:3])]
    return []


def check_exact_values(clause):
    """'ровно N' style parameters (no range) on dimensions etc. are a classic restrictive pattern."""
    t = clause["clause_text"]; tl = t.lower()
    if _is_whitelisted(tl) or RANGE_WORDS.search(tl): return []
    dims = re.findall(rf"(?:длин|ширин|высот|глубин|диаметр|толщин|масса|вес)[^.;\n]{{0,25}}?({NUM})\s*({UNIT_ALT})", tl)
    if len(dims) >= 2:
        return [_f(clause, "COMPETITION", "EXCESSIVE_PARAMETER", "RISK",
                   "Несколько габаритных/весовых характеристик заданы точными значениями без допуска или диапазона.",
                   [{"type": "rule", "id": R_PRINC}, {"type": "rule", "id": R_EQUIV}],
                   proposed="Задать диапазон или допуск («не более», «от … до»), если точное значение не обусловлено совместимостью.", confidence=0.55)]
    return []


def check_qualification(clause):
    tl = clause["clause_text"].lower()
    if _is_whitelisted(tl): return []
    if re.search(r"опыт\w* (выполнени|поставк|оказани)[^.;\n]{0,80}не менее\s*\d", tl) or re.search(r"наличи\w+ (в штате|персонала|сотрудников)[^.;\n]{0,60}не менее\s*\d", tl):
        return [_f(clause, "COMPETITION", "RESTRICTIVE_QUALIFICATION", "RISK",
                   "Количественное требование к опыту/персоналу участника: допустимо только если предусмотрено Положением о закупке и соразмерно предмету.",
                   [{"type": "rule", "id": R_EQUAL}, {"type": "rule", "id": R_PRINC}],
                   proposed="Проверить соответствие Положению о закупке; при использовании как критерия оценки, а не допуска, указать порядок оценки.", confidence=0.6,
                   disposition="INSUFFICIENT_EVIDENCE")]
    return []


CLAUSE_CHECKS = [check_missing_units, check_vague, check_gost, check_brand, check_exact_values, check_qualification]
DOC_CHECKS = [check_contradictions, check_sections]


_role_model = None


def _scope_all(clauses, min_conf=0.8):
    """Heuristic scope for every clause; overridden by the fine-tuned clause-role model (models/clause-role) when it is
    confident. Filename-based CONTRACT decisions are kept, the model only re-decides text-based cases."""
    global _role_model
    for c in clauses: c["scope"] = clause_scope(c); c["scope_method"] = "heuristic"
    try:
        from . import finetune
        if _role_model is None and finetune.available(): _role_model = finetune.ClauseRole()
    except Exception as ex:  # noqa  transformers missing or weights broken: heuristics only
        _role_model = False
    if not _role_model: return
    idx = [i for i, c in enumerate(clauses) if not any(k in (c.get("document_name") or "").lower() for k in ("договор", "контракт"))]
    preds = _role_model.predict([clauses[i]["clause_text"] for i in idx])
    for i, (lab, conf) in zip(idx, preds):
        if conf >= min_conf and lab != clauses[i]["scope"]:
            clauses[i]["scope"], clauses[i]["scope_method"], clauses[i]["scope_conf"] = lab, "model", round(conf, 3)


def run_checks(clauses):
    """clauses: dicts with clause_id, procurement_id, clause_text, position_start/end, page_number, document_name (optional).
    Completeness/competition checks run on TECHNICAL clauses only; document-level checks see everything."""
    out = []
    _scope_all(clauses)
    for c in clauses:
        if c["scope"] != "TECHNICAL": continue
        for chk in CLAUSE_CHECKS:
            out.extend(chk(c))
    tech = [c for c in clauses if c["scope"] == "TECHNICAL"]
    for chk in DOC_CHECKS:
        out.extend(chk(tech if chk is check_contradictions else clauses))
    # identical clauses recur across document editions (v1, v2 of the same ТЗ): keep one finding per (label, text)
    seen, uniq = set(), []
    for f in out:
        key = (f["label"], re.sub(r"\s+", " ", f["clause_text"]).lower()[:300])
        if key in seen: continue
        seen.add(key); f["scope"] = "TECHNICAL"; uniq.append(f)
    return uniq
