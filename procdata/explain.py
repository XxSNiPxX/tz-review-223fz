"""Tier 3: evidence-only explanation and correction with a local LLM (Qwen2.5-7B-Instruct GGUF via llama.cpp).

The model receives ONE finding and the resolved evidence objects. It must answer in JSON and may cite only the
evidence ids it was given; anything else is rejected and the deterministic explanation is kept instead.
Without the model file the engine falls back to the rule-based explanation, so the pipeline always completes.
"""
import json, re
from pathlib import Path
from .common import ROOT, log

_llm = None


def _gguf():
    cands = sorted((ROOT / "models").glob("*.gguf"), key=lambda p: p.stat().st_size, reverse=True) if (ROOT / "models").exists() else []
    return cands[0] if cands else ROOT / "models" / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"


GGUF = _gguf()

SYSTEM = ("Ты эксперт по закупкам по 223-ФЗ. Тебе дают ОДНО замечание к техническому заданию, точный список проблемных мест "
          "и доказательства (нормы, прецеденты ФАС, словарь). Правила:\n"
          "1) Объясняй только указанную проблему и только указанные проблемные места; не ищи других недостатков.\n"
          "2) proposed_text = исходный фрагмент с минимальной правкой ТОЛЬКО проблемных мест. Остальной текст не менять. "
          "Запрещено менять «не менее»/«не более»/диапазоны на точные значения («ровно»), добавлять новые характеристики, "
          "марки, материалы или числа, которых нет в фрагменте. Неизвестное значение пиши как [значение] или [ед. изм.].\n"
          "3) Опирайся только на переданные доказательства; в cited перечисли id использованных; если среди доказательств "
          "есть норма (id вида 223ФЗ_...), сошлись на неё.\n"
          "Отвечай строго JSON: {\"explanation\": str, \"proposed_text\": str, \"cited\": [id,...], \"confidence\": 0..1}")
FORBIDDEN_IN_PROPOSAL = re.compile(r"\bровно\b", re.I)


LLM_LABELS = {"BRAND_REFERENCE", "NO_EQUIVALENT", "EXCESSIVE_PARAMETER", "RESTRICTIVE_QUALIFICATION",
              "CONTRADICTORY_REQUIREMENTS", "INCOMPLETE_STANDARD_REFERENCE", "VAGUE_REQUIREMENT"}


def wants_llm(finding):
    return finding.get("label") in LLM_LABELS and finding.get("disposition") != "PASSED"


def available():
    global GGUF
    GGUF = _gguf()
    return GGUF.exists() and GGUF.stat().st_size > 1_000_000_000


def llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(model_path=str(GGUF), n_ctx=8192, n_threads=12, verbose=False)
    return _llm


def explain(finding, evidence_objects, max_tokens=900):
    """evidence_objects: list of {id, type, text}. Returns finding with explanation/proposed_text/cited updated or unchanged."""
    if not available():
        finding["method"] = finding.get("method", "RULE"); return finding
    ev = "\n".join(f"[{e['id']}] ({e['type']}) {e['text'][:900]}" for e in evidence_objects)
    matched = ", ".join(map(str, finding.get("matched") or [])) or "см. автоматическое пояснение"
    user = (f"Замечание: {finding['label']} ({finding['analysis_type']}, {finding['severity']}).\n"
            f"Проблемные места (менять только их): {matched}\n"
            f"Фрагмент ТЗ: «{finding['clause_text'][:700]}»\n"
            f"Автоматическое пояснение: {finding['explanation']}\n\nДоказательства:\n{ev}\n"
            f"Допустимые id для cited (копировать точно): {', '.join(e['id'] for e in evidence_objects)}\n"
            f"proposed_text: не длиннее 500 символов; если фрагмент длиннее, приведи только исправленное предложение.\n\nОтвет JSON:")
    try:
        out = llm().create_chat_completion(messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                           temperature=0.1, max_tokens=max_tokens, response_format={"type": "json_object"})
        txt = out["choices"][0]["message"]["content"]
        data = json.loads(txt)
    except Exception as ex:  # noqa
        log.warning("llm failed: %s", ex); return finding
    allowed = {e["id"] for e in evidence_objects}
    cited = [c for c in data.get("cited", []) if c in allowed]
    bad = [c for c in data.get("cited", []) if c not in allowed]
    if bad or not cited:
        log.info("llm cited unknown evidence %s; keeping rule explanation", bad); finding["llm_rejected"] = "unknown_citation"; return finding
    prop = data.get("proposed_text") or ""
    src = finding["clause_text"]
    matched = [str(m) for m in (finding.get("matched") or []) if str(m).strip()]
    expl = (data.get("explanation") or "").lower()
    if matched and not any(m.lower() in expl for m in matched):
        # the model explained something other than what the rule flagged (e.g. blamed «не менее» instead of «и т.д.»)
        log.info("llm explanation ignores matched terms %s; keeping rule explanation", matched); finding["llm_rejected"] = "off_target"; return finding
    new_numbers = set(re.findall(r"\d+(?:[.,]\d+)?", prop)) - set(re.findall(r"\d+(?:[.,]\d+)?", src))
    if FORBIDDEN_IN_PROPOSAL.search(prop) or len(new_numbers) > 2 or len(prop) > 2.5 * max(len(src), 80):
        log.info("llm proposal rejected (invented values / exact-value rewrite / too long)"); finding["llm_rejected"] = "unsafe_proposal"
        data["proposed_text"] = finding.get("proposed_text")   # keep the rule-based suggestion, use the explanation only
    finding.update({"explanation": data.get("explanation", finding["explanation"]), "proposed_text": data.get("proposed_text") or finding.get("proposed_text"),
                    "cited": cited, "method": finding.get("method", "RULE") + "+LLM", "llm_confidence": data.get("confidence")})
    return finding
