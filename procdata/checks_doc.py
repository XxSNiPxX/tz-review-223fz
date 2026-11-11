"""Document-level checks over the structured ingest output (sections, attributes, items, fields).

These are the error classes the case examples are made of: cross-section contradictions, warranty basis vs
contract kind, standard designations, ОКПД2 consistency, kits without composition, items without characteristics,
provisions that do not belong in a ТЗ. Each finding carries the case category (CASE_CATEGORIES) and anchors.
"""
import json, re, uuid
from pathlib import Path
from .common import ROOT, log

CASE_CATEGORIES = {   # case-brief category -> our analysis_type
    "CONTRADICTION": "COMPLETENESS", "INCORRECT_CHARACTERISTIC": "COMPLETENESS", "COMPLETENESS": "COMPLETENESS",
    "STANDARDS": "COMPLIANCE", "WRONG_OKPD2": "COMPLIANCE", "WARRANTY": "COMPLIANCE", "OUT_OF_SCOPE_PROVISION": "COMPLIANCE",
    "COMPETITION_RESTRICTION": "COMPETITION", "FORM": "COMPLETENESS",
}
REG_PATH = ROOT / "kb" / "standards_registry.json"
OKPD_PATH = ROOT / "kb" / "okpd2" / "okpd2.json"
_reg = _okpd = None


def registry():
    global _reg
    if _reg is None:
        _reg = json.loads(REG_PATH.read_text(encoding="utf-8")) if REG_PATH.exists() else {}
    return _reg


def okpd():
    """{code: name}; accepts the prog815 json (list of dicts or dict) or any {code:name} mapping."""
    global _okpd
    if _okpd is None:
        _okpd = {}
        if OKPD_PATH.exists():
            try:
                raw = OKPD_PATH.read_text(encoding="utf-8")
                try:
                    data = json.loads(raw, strict=False)
                except json.JSONDecodeError:
                    data = json.loads(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw), strict=False)
                if isinstance(data, dict) and all(isinstance(v, str) for v in list(data.values())[:5]):
                    _okpd = data
                else:
                    items = data if isinstance(data, list) else data.get("items") or data.get("data") or list(data.values())
                    for it in items:
                        if isinstance(it, dict):
                            code = it.get("c") or it.get("code") or it.get("Код") or it.get("kod") or it.get("id")
                            name = it.get("n") or it.get("name") or it.get("Наименование") or it.get("title") or ""
                            if code: _okpd[str(code).strip()] = str(name)
            except Exception as ex:  # noqa
                log.warning("okpd2 load failed: %s", ex)
    return _okpd


def _f(doc, category, label, severity, explanation, anchors, evidence, proposed=None, confidence=0.8, disposition="FLAGGED", clause_text="", clause_id=None, matched=None):
    return {"finding_id": "F_" + uuid.uuid4().hex[:10], "clause_id": clause_id, "procurement_id": None, "page": None,
            "analysis_type": CASE_CATEGORIES[category], "case_category": category, "label": label, "severity": severity,
            "disposition": disposition, "evidence": evidence, "explanation": explanation, "proposed_text": proposed,
            "confidence": confidence, "method": "RULE", "clause_text": clause_text[:600], "anchors": anchors, "matched": matched or [], "scope": "TECHNICAL"}


# ----------------------------------------------------------------- helpers
NUM = r"\d+(?:[.,]\d+)?"
DIM = re.compile(rf"({NUM})\s*[xх×]\s*({NUM})(?:\s*[xх×]\s*({NUM}))?")
ATTR_KEYS = {  # attribute family -> (name patterns, value extractor kind)
    "тип лифта": (r"тип лифта|^тип$", "cat:пассажирск|грузов|больничн|грузопассажирск"),
    "грузоподъемность": (r"грузоподъ[её]мност", "num:кг"),
    "скорость": (r"^скорость", "num:м/с"),
    "количество остановок": (r"количество остановок|остановк", "num:"),
    "проем двери": (r"про[её]м двер|размер двер|двер\w* про[её]м", "dim:"),
    "высота подъема": (r"высота подъ[её]ма", "num:м"),
    "напряжение": (r"напряжени", "num:в"),
    "мощность": (r"^мощност", "num:квт"),
    "срок службы": (r"срок службы", "num:лет"),
    "гарантийный срок": (r"гарантийн\w* срок", "num:мес"),
    "срок поставки": (r"срок поставки|срок выполнения", "num:дн"),
    "объем": (r"объ[её]м(?!\s*поставки)", "num:л"),
    "класс точности": (r"класс точности", "num:"),
    "диапазон": (r"диапазон измерен", "range:"),
}


def _family(name):
    n = name.lower().strip()
    for fam, (pat, _) in ATTR_KEYS.items():
        if re.search(pat, n): return fam
    return None


def _value(fam, text):
    kind = ATTR_KEYS[fam][1]
    t = text.lower().replace(",", ".")
    if kind.startswith("cat:"):
        m = re.search(kind[4:], t); return m.group(0)[:6] if m else None
    if kind.startswith("dim:"):
        m = DIM.search(t); return "x".join(g for g in m.groups() if g) if m else None
    m = re.search(rf"(?<![\d.])({NUM})(?![\d.])", t)
    if not m: return None
    v = m.group(1)
    return (v.rstrip("0").rstrip(".") if "." in v else v)


def _mentions(doc, fam):
    """All places (attributes, items, subject, prose) where the family appears with a value."""
    out = []
    for a in doc["attributes"]:
        if _family(a["name"]) == fam:
            v = _value(fam, a["value"])
            if v: out.append((v, a["anchor"], f"{a['name']}: {a['value']}", a.get("row_id") or a.get("anchor")))
    pat = ATTR_KEYS[fam][0]
    for c in doc["clauses"]:
        if c.get("table_id") and any(a.get("row_id") == c["clause_id"] for a in doc["attributes"]): continue
        tl = c["clause_text"].lower()
        if fam == "тип лифта":
            m = re.search(r"(пассажирск|грузов(?!ой\s+автомобил)|больничн)\w*\s+лифт|лифт\w*\s+(пассажирск|грузов|больничн)", tl)
            if m:
                v = (m.group(1) or m.group(2))[:6]; out.append((v, c["anchor"], c["clause_text"][:160], c["clause_id"]))
        elif fam == "грузоподъемность":
            for m in re.finditer(rf"грузоподъ[её]мност\w*\s*(?:[:\-–—]|до|не менее)?\s*({NUM})\s*кг", tl):
                out.append((m.group(1).replace(",", "."), c["anchor"], c["clause_text"][:160], c["clause_id"]))
        elif fam == "проем двери":
            for m in re.finditer(rf"(?:двер\w*|про[её]м\w*)[^.;|\n]{{0,40}}?({NUM}\s*[xх×]\s*{NUM})", tl):
                out.append((re.sub(r"\s", "", m.group(1)).replace("х", "x").replace("×", "x"), c["anchor"], c["clause_text"][:160], c["clause_id"]))
        elif fam == "количество остановок":
            for m in re.finditer(rf"на\s*(\d+)\s*останов", tl):
                out.append((m.group(1), c["anchor"], c["clause_text"][:160], c["clause_id"]))
    return out


# ----------------------------------------------------------------- checks
UNIT_IN_NAME = re.compile(r",\s*(м²|м2|кв\.?\s*м|м³|м3|кг|т|мм|см|м|км|л|шт\.?|мес\.?|мес|лет|дн\.?|дней|ч|час|кВт|Вт|В|А|°C|%|чел\.?|ед\.?)\s*$", re.I)


def check_generic_attribute_contradictions(doc):
    """Attribute table says «Общая площадь помещений, м² | 1500» while the prose says «площадь ... 1200 м²»."""
    out = []
    for a in doc["attributes"]:
        m = UNIT_IN_NAME.search(a["name"])
        if not m or a.get("table_id") is None: continue
        unit = m.group(1).lower().replace("кв. м", "м²").replace("кв.м", "м²").replace("м2", "м²")
        v = _value("объем", a["value"])
        if v is None: continue
        head = re.sub(UNIT_IN_NAME, "", a["name"]).lower()
        nouns = [w for w in re.findall(r"[а-яё]{5,}", head) if w[:5] not in ("общая", "общий", "общее", "колич", "макси", "миним")]
        if not nouns: continue
        stem = nouns[0][:6]
        unit_re = re.escape(m.group(1)).replace("м²", "(?:м²|м2|кв\\.?\\s*м)")
        pat = re.compile(stem + r"[а-яё]*[^.;|\n]{0,80}?(?<![\d.,])(" + NUM + r")\s*(?:" + unit_re + r")(?![а-яa-z])", re.I)
        others = {}
        for c in doc["clauses"]:
            if c.get("table_id") == a.get("table_id"): continue
            for mm in pat.finditer(c["clause_text"].replace(",", ".") if "," in c["clause_text"] and not re.search(r"\d,\d", c["clause_text"]) else c["clause_text"]):
                val = _value("объем", mm.group(1))
                if val and val != v: others.setdefault(val, []).append((c["anchor"], c["clause_text"][:160], c["clause_id"]))
        if others:
            desc = "; ".join(f"«{k} {unit}» ({vv[0][0]})" for k, vv in others.items())
            out.append(_f(doc, "CONTRADICTION", "CONTRADICTORY_REQUIREMENTS", "ERROR",
                          f"«{a['name']}»: в таблице указано {v} {unit}, а в тексте — {desc}.", [a["anchor"]] + [vv[0][0] for vv in others.values()],
                          [{"type": "doc", "id": "internal_consistency"}, {"type": "rule", "id": "223ФЗ_ART4_P10"}],
                          proposed="Оставить одно значение во всех частях ТЗ или явно разделить объекты, к которым относятся разные значения.",
                          confidence=0.8, clause_text=f"{a['name']}: {a['value']} || " + next(iter(others.values()))[0][1], clause_id=a.get("row_id"),
                          matched=[str(v)] + list(others)))
    return out


def check_contradictions(doc):
    out = []
    for fam in ("тип лифта", "грузоподъемность", "проем двери", "количество остановок", "скорость", "высота подъема", "напряжение", "гарантийный срок"):
        ms = _mentions(doc, fam)
        vals = {}
        for v, anchor, text, cid in ms:
            vals.setdefault(v, []).append((anchor, text, cid))
        if len(vals) > 1:
            desc = "; ".join(f"«{v}» ({len(a)}×: {a[0][0]})" for v, a in vals.items())
            majority = max(vals.items(), key=lambda kv: len(kv[1]))[0]
            minority = [v for v in vals if v != majority]
            first = next(iter(vals.values()))[0]
            out.append(_f(doc, "CONTRADICTION", "CONTRADICTORY_REQUIREMENTS", "ERROR",
                          f"Характеристика «{fam}» задана по-разному в разных частях ТЗ: {desc}. Предмет закупки, таблица характеристик и спецификация должны совпадать.",
                          [a for v in vals.values() for a, _, _ in v][:6], [{"type": "doc", "id": "internal_consistency"}, {"type": "rule", "id": "223ФЗ_ART4_P10"}],
                          proposed=f"Привести все упоминания к одному значению (в документе преобладает «{majority}»; расходятся: {', '.join(minority)}). Если разные значения относятся к разным объектам, явно разделить их.",
                          confidence=0.85, clause_text=" || ".join(t for v in vals.values() for _, t, _ in v[:1]), clause_id=first[2],
                          matched=[str(v) for v in vals]))
    return out


def check_dimension_pairs(doc):
    out, groups = [], {}
    for c in doc["clauses"]:
        for m in DIM.finditer(c["clause_text"].replace(",", ".")):
            w, h, d = m.group(1), m.group(2), m.group(3)
            if d: continue                                   # 3-D sizes are products, not openings
            groups.setdefault(w, {}).setdefault(h, []).append((c["anchor"], c["clause_text"][:140], c["clause_id"]))
    for w, hs in groups.items():
        if len(hs) > 1 and any(int(float(w)) >= 500 for _ in [0]):
            desc = "; ".join(f"{w}×{h} ({v[0][0]})" for h, v in hs.items())
            first = next(iter(hs.values()))[0]
            out.append(_f(doc, "CONTRADICTION", "DIMENSION_MISMATCH", "RISK",
                          f"Один и тот же размер по ширине {w} встречается с разной высотой: {desc}. Если это один проем/дверь, значения противоречат друг другу.",
                          [v[0][0] for v in hs.values()], [{"type": "doc", "id": "internal_consistency"}],
                          proposed="Уточнить, относятся ли размеры к одному объекту, и оставить одно значение.", confidence=0.5, disposition="INSUFFICIENT_EVIDENCE",
                          clause_text=" || ".join(v[0][1] for v in hs.values()), clause_id=first[2], matched=[f"{w}x{h}" for h in hs]))
    return out


def check_warranty_basis(doc):
    out = []
    kind = doc["fields"].get("contract_kind")
    for c in doc["clauses"]:
        tl = c["clause_text"].lower()
        if "гарантийн" not in tl or "с момента" not in tl and "с даты" not in tl: continue
        if kind == "WORKS" and re.search(r"товарн\w+ накладн|приемк\w+ товара|поставленн\w+ товара", tl):
            out.append(_f(doc, "WARRANTY", "WARRANTY_BASIS_MISMATCH", "ERROR",
                          "Предмет закупки — работы (подряд), а гарантийный срок отсчитывается от товарной накладной / приемки товара. Для работ основание — акт о приемке выполненных работ (КС-2) и справка о стоимости (КС-3) либо иной акт приемки работ.",
                          [c["anchor"]], [{"type": "rule", "id": "GK_RF_ART724"}, {"type": "rule", "id": "GK_RF_ART753"}, {"type": "doc", "id": "KS-2/KS-3 (Постановление Госкомстата № 100)"}],
                          proposed="«…с момента подписания сторонами Актов о приемке выполненных работ по форме КС-2 и справки о стоимости выполненных работ и затрат по форме КС-3».",
                          confidence=0.85, clause_text=c["clause_text"], clause_id=c["clause_id"], matched=["товарной накладной"]))
        if kind == "SERVICES" and re.search(r"товарн\w+ накладн|кс-2|кс-3", tl):
            out.append(_f(doc, "WARRANTY", "WARRANTY_BASIS_MISMATCH", "ERROR",
                          "Предмет закупки — услуги, а гарантийный срок отсчитывается от товарной накладной / актов КС-2, КС-3. Для услуг основание — акт сдачи-приемки оказанных услуг.",
                          [c["anchor"]], [{"type": "rule", "id": "GK_RF_ART783"}, {"type": "rule", "id": "GK_RF_ART720"}], proposed="«…с даты подписания сторонами акта сдачи-приемки оказанных услуг».",
                          confidence=0.8, clause_text=c["clause_text"], clause_id=c["clause_id"], matched=["товарной накладной"]))
        if kind == "GOODS" and re.search(r"кс-2|кс-3|акт\w* выполненных работ", tl):
            out.append(_f(doc, "WARRANTY", "WARRANTY_BASIS_MISMATCH", "ERROR",
                          "Предмет закупки — поставка товара, а гарантия отсчитывается от актов выполненных работ (КС-2/КС-3). Для поставки основание — товарная накладная / акт приема-передачи товара.",
                          [c["anchor"]], [{"type": "rule", "id": "GK_RF_ART470"}], proposed="«…с даты подписания товарной накладной (акта приема-передачи Товара)».",
                          confidence=0.8, clause_text=c["clause_text"], clause_id=c["clause_id"]))
    return out


GOST_ANY = re.compile(r"ГОСТ(\s*Р)?(\s*ИСО)?(\s*МЭК)?\s*(\d[\d.]*)(?:-(\d{2,4}))?")


def check_standards(doc):
    out, seen = [], set()
    reg = registry()
    for c in doc["clauses"]:
        for m in GOST_ANY.finditer(c["clause_text"]):
            has_r, num, yr = bool(m.group(1)), m.group(4), m.group(5)
            key = (has_r, num)
            if key in seen: continue
            seen.add(key)
            entry = reg.get(f"ГОСТ {num}")
            canonical_r = entry and entry["canonical_family"].startswith("ГОСТ Р")
            # national standards adopted after 1992 carry 5-digit numbers 5xxxx..6xxxx (ГОСТ Р 5xxxx-20xx); interstate ГОСТ keep older numbering
            looks_national = (not has_r) and re.fullmatch(r"5\d{4}(?:\.\d+)?", num) and yr and int(yr) >= 2000
            if looks_national or (canonical_r and not has_r):
                out.append(_f(doc, "STANDARDS", "STANDARD_DESIGNATION", "ERROR" if canonical_r else "RISK",
                              f"Обозначение «ГОСТ {num}-{yr or ''}» выглядит как национальный стандарт ГОСТ Р (номер 5xxxx, год ≥ 2000" + (", в корпусе закупок обозначается как ГОСТ Р" if canonical_r else "") + "). Без «Р» ссылка указывает на несуществующий межгосударственный стандарт.",
                              [c["anchor"]], [{"type": "doc", "id": "ГОСТ Р 1.5-2012 (обозначение национальных стандартов)"}] + ([{"type": "registry", "id": f"ГОСТ {num}"}] if entry else []),
                              proposed=f"ГОСТ Р {num}-{yr}" if yr else f"ГОСТ Р {num}", confidence=0.8 if canonical_r else 0.6,
                              disposition="FLAGGED" if canonical_r else "INSUFFICIENT_EVIDENCE", clause_text=c["clause_text"], clause_id=c["clause_id"], matched=[m.group(0)]))
            if not yr and not entry:
                out.append(_f(doc, "STANDARDS", "INCOMPLETE_STANDARD_REFERENCE", "NOTE",
                              f"Стандарт «{m.group(0).strip()}» указан без года принятия; проверить актуальность и полное обозначение.", [c["anchor"]],
                              [{"type": "doc", "id": "ГОСТ Р 1.5-2012"}], proposed=f"{m.group(0).strip()}-[год]", confidence=0.5, disposition="INSUFFICIENT_EVIDENCE",
                              clause_text=c["clause_text"], clause_id=c["clause_id"], matched=[m.group(0)]))
    return out


def check_okpd2(doc):
    out = []
    codes = okpd()
    kind = doc["fields"].get("contract_kind")
    items = doc["items"]
    seen = set()
    for it in items:
        code = it.get("okpd2")
        if not code: continue
        key = (code, (it.get("name") or "").strip().lower())
        if key in seen: continue                 # the same position listed in two tables
        seen.add(key)
        name = (it.get("name") or "").lower()
        if codes and code not in codes:
            out.append(_f(doc, "WRONG_OKPD2", "OKPD2_UNKNOWN_CODE", "ERROR", f"Код ОКПД2 {code} отсутствует в классификаторе ОК 034-2014.", [it["anchor"]],
                          [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], proposed="Выбрать действующий код из классификатора.", confidence=0.9, clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
            continue
        parts = code.split(".")
        if len(parts) < 4 or parts[-1].endswith("0") and parts[-1] in ("190", "900", "000", "110") and codes:
            # generic ".190 / .900" buckets when more specific children exist
            children = [k for k in codes if k.startswith(".".join(parts[:3]) + ".") and k != code] if codes else []
            if children and parts[-1] in ("190", "900"):
                out.append(_f(doc, "WRONG_OKPD2", "OKPD2_TOO_GENERIC", "RISK",
                              f"Код {code} («{codes.get(code, '')[:60]}») — обобщающая позиция «прочие»; в группе есть более точные коды ({', '.join(children[:4])}…). Для «{it['name'][:50]}» требуется проверить, нет ли точного кода.",
                              [it["anchor"]], [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], proposed="Уточнить код до конкретной подкатегории.", confidence=0.55, disposition="INSUFFICIENT_EVIDENCE",
                              clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
        sec = int(parts[0])
        is_works_code = 41 <= sec <= 43
        is_service_code = sec >= 45 and sec != 58
        name_is_goods = not re.search(r"^(услуг|работ|выполнени|оказани|поставк[аи] и монтаж)", name) and not re.search(r"\b(услуг|работ)\w*\b", name[:40])
        name_is_work = bool(re.search(r"^(работ|выполнени)|\bработ\w*\b", name[:40]))
        name_is_service = bool(re.search(r"^(услуг|оказани)|\bуслуг\w*\b", name[:40]))
        if name_is_goods and (is_works_code or is_service_code):
            out.append(_f(doc, "WRONG_OKPD2", "OKPD2_KIND_MISMATCH", "ERROR",
                          f"Позиция «{it['name'][:60]}» — товар, а код {code} («{codes.get(code, '')[:50]}») относится к {'работам' if is_works_code else 'услугам'}.",
                          [it["anchor"]], [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], proposed="Указать код товара (разделы 01–33), например из группы 28.xx для машин и оборудования.",
                          confidence=0.8, clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
            continue
        if (name_is_service and not is_service_code) or (name_is_work and not is_works_code and sec < 41):
            out.append(_f(doc, "WRONG_OKPD2", "OKPD2_KIND_MISMATCH", "RISK",
                          f"Позиция «{it['name'][:60]}» — {'услуги' if name_is_service else 'работы'}, а код {code} относится к другому виду объекта закупки.",
                          [it["anchor"]], [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], confidence=0.6, disposition="INSUFFICIENT_EVIDENCE",
                          clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
            continue
        if kind == "GOODS" and is_works_code:
            out.append(_f(doc, "WRONG_OKPD2", "OKPD2_KIND_MISMATCH", "ERROR", f"Предмет — поставка товара, а код {code} относится к строительным работам (разделы 41–43).", [it["anchor"]],
                          [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], proposed="Указать код товара (разделы 01–33).", confidence=0.8, clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
        if kind == "WORKS" and not is_works_code and sec < 41 and "лифт" not in name:
            out.append(_f(doc, "WRONG_OKPD2", "OKPD2_KIND_MISMATCH", "RISK", f"Предмет — работы, а код {code} относится к товарам; допустимо только для отдельно поставляемого оборудования.", [it["anchor"]],
                          [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}], confidence=0.6, disposition="INSUFFICIENT_EVIDENCE", clause_text=f"{it['name']} | {code}", clause_id=it["row_id"], matched=[code]))
    # works that include supply of equipment, but the specification lists no goods line
    text = " ".join(c["clause_text"].lower() for c in doc["clauses"])
    if kind in ("WORKS", "MIXED") and re.search(r"поставк\w+ (нового|оборудовани|лифт)|закупк\w+ нового", text) and items and all(41 <= int(i["okpd2"].split(".")[0]) <= 43 for i in items if i.get("okpd2")):
        out.append(_f(doc, "WRONG_OKPD2", "OKPD2_MISSING_GOODS_LINE", "ERROR",
                      "Состав работ включает поставку оборудования, но спецификация содержит только код работ (43.xx). Поставляемое оборудование должно быть отдельной позицией со своим кодом ОКПД2 (товар), иначе предмет закупки и спецификация расходятся.",
                      [i["anchor"] for i in items[:2]], [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}, {"type": "rule", "id": "223ФЗ_ART4_P10"}],
                      proposed="Добавить в спецификацию позицию с поставляемым оборудованием (например, «Лифт грузовой — шт. — 1 — 28.22.16.11x») и оставить работы отдельной строкой.",
                      confidence=0.75, clause_text=" | ".join(f"{i['name']} {i['okpd2']}" for i in items[:2]), clause_id=items[0]["row_id"]))
    return out


def check_kits_and_items(doc):
    out = []
    subj = (doc["fields"].get("subject") or "").lower()
    subj_stems = {w[:6] for w in re.findall(r"[а-яё]{5,}", subj)}
    items, seen_names = [], set()
    for i in doc["items"]:
        nm = (i.get("name") or "").strip()
        if not nm or re.fullmatch(r"\d+\.?", nm) or not (i.get("qty") or i.get("okpd2")) or i.get("kind") == "WORKS": continue
        stems = {w[:6] for w in re.findall(r"[а-яё]{5,}", nm.lower())}
        if len(stems) >= 3 and len(stems & subj_stems) >= 3: continue          # restates the subject line / caption
        if nm.lower() in seen_names: continue                                   # same item listed in two tables
        seen_names.add(nm.lower()); items.append(i)
    def _attr_row_for(it):
        words = [w[:6] for w in re.findall(r"[а-яё]{5,}", it["name"].lower())][:3]
        best = None
        for a in doc["attributes"]:
            n = a["name"].lower()
            score = sum(w in n for w in words)
            if score >= max(1, len(words) - 1) and (best is None or score > best[0]): best = (score, a)
        return best[1] if best else None
    attr_text = " ".join(a["name"].lower() + " " + a["value"].lower() for a in doc["attributes"]) + " " + " ".join(c["clause_text"].lower() for c in doc["clauses"] if c.get("table_id"))
    for it in items:
        n = it["name"].lower()
        is_kit = bool(re.search(r"^(комплект|набор|комплекс)\s+[а-яё]", n) or re.search(r"комплекс оборудования|измерительный комплект|^стенд|стенд\b", n)) \
                 and not re.search(r"^(набор|комплект) (щуп|шаблон|ключ|сверл|бит|надфил|плашек|метчик|головок|отверт|гаечн|торцев|калибр|концевых мер|мер длины|гирь|фильтр|прокладок|уплотнен|крепеж|постельн)", n)
        if is_kit:
            row = _attr_row_for(it)
            val = (row["value"] if row else "")
            n_qty = len(re.findall(r"\d+\s*(?:шт|компл|ед)\b", val.lower()))
            n_bullets = val.count("•") + val.count(";")
            has_composition = n_qty >= 2 or (n_bullets >= 4 and re.search(r"состав|в комплект", val.lower()))
            if has_composition:
                out.append(_f(doc, "COMPLETENESS", "KIT_SHOULD_BE_SPLIT", "RISK",
                              f"Позиция «{it['name'][:70]}» объединяет несколько разнородных изделий под одним кодом ОКПД2 ({it.get('okpd2') or 'код не указан'}). Разные изделия имеют разные коды и по-разному попадают в перечень закупок у СМП; практика ЕИС — отдельные позиции с собственными характеристиками, количеством и кодом.",
                              [it["anchor"]], [{"type": "doc", "id": "ОК 034-2014 (ОКПД2)"}, {"type": "doc", "id": "Постановление Правительства РФ от 11.12.2014 № 1352 (перечень СМП)"}],
                              proposed="Раскрыть комплект на отдельные позиции спецификации с кодами ОКПД2 и количеством; описание состава перенести в характеристики каждой позиции.",
                              confidence=0.6, disposition="INSUFFICIENT_EVIDENCE", clause_text=(it["name"] + " — " + val[:300]), clause_id=it["row_id"], matched=[it["name"][:40]]))
            if not has_composition:
                out.append(_f(doc, "COMPLETENESS", "KIT_WITHOUT_COMPOSITION", "ERROR",
                              f"Позиция «{it['name'][:70]}» заявлена как комплект/набор, но состав и количество входящих изделий не раскрыты. Без этого невозможно сопоставить предложения участников и определить код ОКПД2 и принадлежность к перечню СМП.",
                              [it["anchor"]], [{"type": "rule", "id": "223ФЗ_ART3_P6.1"}, {"type": "rule", "id": "223ФЗ_ART4_P10"}],
                              proposed="Раскрыть комплект на отдельные позиции (наименование, характеристики, количество, код ОКПД2) либо привести полный состав комплекта.",
                              confidence=0.75 if not row else 0.6, disposition="FLAGGED" if not row else "INSUFFICIENT_EVIDENCE",
                              clause_text=(it["name"] + (" — " + val[:300] if val else "")), clause_id=it["row_id"], matched=[it["name"][:40]]))
    # items with no characteristics anywhere
    if doc["attributes"] or any(t["kind"] == "ATTRIBUTES" for t in doc["tables"]):
        char_text = " ".join(a["name"].lower() + " " + a["value"].lower() for a in doc["attributes"])
        for it in items:
            if _attr_row_for(it) is not None: continue
            words = [w for w in re.findall(r"[а-яё]{5,}", it["name"].lower())][:2]
            if words and not all(w[:6] in char_text for w in words):
                out.append(_f(doc, "COMPLETENESS", "ITEM_WITHOUT_CHARACTERISTICS", "RISK",
                              f"Для позиции «{it['name'][:70]}» не найдены технические характеристики в разделе требований к товару.", [it["anchor"]],
                              [{"type": "rule", "id": "223ФЗ_ART3_P6.1"}], proposed="Добавить функциональные, технические и качественные характеристики позиции.",
                              confidence=0.55, disposition="INSUFFICIENT_EVIDENCE", clause_text=it["name"], clause_id=it["row_id"], matched=[it["name"][:40]]))
    return out


def check_out_of_scope(doc):
    out = []
    for c in doc["clauses"]:
        tl = c["clause_text"].lower()
        if re.search(r"национальн\w+ режим", tl) and re.search(r"не является|определяется закупочной|не применя", tl):
            out.append(_f(doc, "OUT_OF_SCOPE_PROVISION", "NATIONAL_REGIME_STATEMENT", "RISK",
                          "ТЗ содержит утверждение о применении (неприменении) национального режима. Это предмет закупочной документации и ПП РФ № 1875 (запреты/ограничения/преимущества), а не технического задания; формулировка в ТЗ может противоречить обязательным мерам.",
                          [c["anchor"]], [{"type": "doc", "id": "Постановление Правительства РФ от 23.12.2024 № 1875"}, {"type": "rule", "id": "223ФЗ_ART3.1-4_P1"}],
                          proposed="Удалить фразу из ТЗ; условия национального режима указать в извещении/документации.", confidence=0.7, disposition="INSUFFICIENT_EVIDENCE",
                          clause_text=c["clause_text"], clause_id=c["clause_id"], matched=["национального режима"]))
    return out


def check_title_subject(doc):
    out = []
    subj = (doc["fields"].get("subject") or "").lower()
    verb = "замен" if "замен" in subj else "ремонт" if "ремонт" in subj else "поставк" if "поставк" in subj else None
    if not verb: return out
    caps = [(t.get("caption") or "", t["anchor"], t["table_id"]) for t in doc["tables"]]
    caps += [(c["clause_text"], c["anchor"], c["clause_id"]) for c in doc["clauses"] if re.match(r"\s*спецификаци", c["clause_text"], re.I) and len(c["clause_text"]) < 120]
    for cap_text, anchor, cid in caps:
        cap = cap_text.lower()
        t = {"caption": cap_text, "anchor": anchor, "table_id": cid}
        for v in ("ремонт", "замен", "поставк"):
            if v != verb and v in cap and verb not in cap:
                out.append(_f(doc, "CONTRADICTION", "TITLE_SUBJECT_MISMATCH", "RISK",
                              f"Заголовок спецификации «{t['caption'][:80]}» говорит о «{v}…», а предмет закупки — «{verb}…».", [t["anchor"]],
                              [{"type": "doc", "id": "internal_consistency"}], proposed=f"Привести заголовок спецификации к предмету закупки.", confidence=0.6,
                              clause_text=t["caption"], clause_id=t["table_id"], matched=[v]))
    return out


def check_numbers_in_words(doc):
    out = []
    for c in doc["clauses"]:
        t = c["clause_text"]
        if re.search(r"срок\w*\s+[^.\n]{0,60}?\b(\d{1,4})\s*(календарн|рабоч|дн|мес)", t, re.I) and not re.search(r"\d\s*\(", t):
            out.append(_f(doc, "FORM", "NUMBER_WITHOUT_WORDS", "NOTE", "Срок указан только цифрами; в закупочной документации принято дублировать прописью для защиты от разночтений.",
                          [c["anchor"]], [{"type": "doc", "id": "practice"}], proposed="«105 (Сто пять) календарных дней»", confidence=0.4, disposition="INSUFFICIENT_EVIDENCE",
                          clause_text=t, clause_id=c["clause_id"]))
    return out


def check_commissioning_per_item(doc):
    """Goods with several positions: if the ТЗ mentions commissioning/training/installation only globally, each position
    should say whether it needs them (the reviewers added «ПНР — требуются/не требуются» per item)."""
    out = []
    if doc["fields"].get("contract_kind") not in ("GOODS", "MIXED"): return out
    items = [i for i in doc["items"] if i.get("qty") or i.get("okpd2")]
    if len(items) < 3: return out
    text = " ".join(c["clause_text"].lower() for c in doc["clauses"])
    if not re.search(r"пусконалад|пнр|инструктаж|обучени|монтаж", text): return out
    rows_with = sum(1 for a in doc["attributes"] if re.search(r"пусконалад|пнр|инструктаж|монтаж", a["value"].lower()))
    if rows_with < max(1, len(items) // 3):
        anchor = next((c["anchor"] for c in doc["clauses"] if re.search(r"пусконалад|инструктаж", c["clause_text"].lower())), None)
        out.append(_f(doc, "COMPLETENESS", "COMMISSIONING_NOT_PER_ITEM", "RISK",
                      f"Пусконаладка / монтаж / инструктаж упомянуты в общих условиях, но из {len(items)} позиций только {rows_with} содержат указание, требуются ли они. Участник не может оценить объем сопутствующих работ по каждой позиции.",
                      [anchor] if anchor else [], [{"type": "rule", "id": "223ФЗ_ART4_P10"}], proposed="Для каждой позиции указать: «ПНР/инструктаж — требуются (объем) / не требуются».",
                      confidence=0.5, disposition="INSUFFICIENT_EVIDENCE", clause_text="; ".join(i["name"][:40] for i in items[:5]), clause_id=items[0]["row_id"]))
    return out


def check_sme_list(doc):
    """If the procurement is SME-only or the ТЗ mentions SME, the goods codes must be checked against the ПП 1352 list.
    The list itself is not in the knowledge base yet, so this is always a manual-review item, never an error."""
    out = []
    text = " ".join(c["clause_text"].lower() for c in doc["clauses"])
    codes = [i for i in doc["items"] if i.get("okpd2")]
    if doc["fields"].get("contract_kind") not in ("GOODS", "MIXED") or not codes: return out
    mentions = bool(re.search(r"субъект\w* малого|смп|мсп", text))
    if True:
        out.append(_f(doc, "COMPETITION_RESTRICTION", "SME_LIST_CHECK", "RISK" if mentions else "NOTE",
                      (f"Закупка упоминает субъектов МСП; " if mentions else "Поставка товаров: ") + f"{len(codes)} кодов ОКПД2 нужно сверить с перечнем товаров, закупаемых только у СМП (ПП РФ № 1352 / перечень заказчика): от этого зависит способ закупки и состав лота. Перечень не входит в базу знаний: ручная проверка.",
                      [codes[0]["anchor"]], [{"type": "doc", "id": "Постановление Правительства РФ от 11.12.2014 № 1352"}], proposed="Сверить коды с перечнем; при несовпадении изменить способ закупки или состав лота.",
                      confidence=0.4, disposition="INSUFFICIENT_EVIDENCE", clause_text=", ".join(i["okpd2"] for i in codes[:10]), clause_id=codes[0]["row_id"], matched=[i["okpd2"] for i in codes[:5]]))
    return out


def run_doc_checks(doc):
    out = []
    for chk in (check_contradictions, check_generic_attribute_contradictions, check_dimension_pairs, check_warranty_basis, check_standards, check_okpd2, check_kits_and_items, check_out_of_scope, check_title_subject, check_numbers_in_words, check_commissioning_per_item, check_sme_list):
        try:
            out.extend(chk(doc))
        except Exception as ex:  # noqa
            log.exception("doc check %s failed", chk.__name__)
    return out
