"""Feedback → datasets → retrain → regression gate → promote. The loop:

  reviews / review_findings / feedback / edits  (written by the server on every action)
        │  export()
        ▼
  data/training/<stamp>/  finding_feedback.jsonl  corrections.jsonl  missed.jsonl  manifest.json
        │  retrain()
        ▼
  finding-filter (TF-IDF + logistic regression: will a reviewer reject this finding?)
        │  gate: eval_case.py on the gold suite must not lose a mandatory item nor add a false positive
        ▼
  models/finding-filter/active.joblib  +  model_registry row (status promoted | rejected)

The filter never deletes a finding: at review time a FLAGGED finding with p(reject) above the threshold is downgraded to
«требует проверки» with an explanation, so the reviewer still sees it.
"""
import datetime, json, re, shutil, uuid
from pathlib import Path
from .common import ROOT, log

OUT = ROOT / "data" / "training"
FILTER_DIR = ROOT / "models" / "finding-filter"
import os
MIN_EXAMPLES, MIN_PER_CLASS = 20, 5
REJECT_THRESHOLD = float(os.environ.get("FILTER_REJECT_THRESHOLD", "0.85"))   # env so the gate subprocess uses the same value


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _text(label, category, clause):
    body = re.sub(r"\s+", " ", clause or "")[:1200]
    return f"[{label}] [{category}] {body}"


def export(conn, out_dir=None):
    out = Path(out_dir) if out_dir else OUT / _stamp(); out.mkdir(parents=True, exist_ok=True)
    # test / synthetic rows never enter training data
    rows = conn.execute("""SELECT f.*, rf.severity, rf.disposition, rf.confidence, rf.method, rf.explanation FROM feedback f
                           LEFT JOIN review_findings rf ON rf.finding_id=f.finding_id
                           WHERE COALESCE(f.source,'') != 'test' AND COALESCE(f.user_id,'') NOT LIKE 'synthetic%' AND COALESCE(f.user_id,'') NOT LIKE 'claude-test%'""").fetchall()
    ff = [{"text": _text(r["label"], r["case_category"], r["clause_text"]), "label": r["label"], "category": r["case_category"],
           "clause_text": r["clause_text"], "verdict": r["verdict"], "y": 1 if r["verdict"] == "confirm" else 0, "correct_category": r["correct_category"],
           "comment": r["comment"], "severity": r["severity"], "disposition": r["disposition"], "source": r["source"], "review_id": r["review_id"]}
          for r in rows if r["verdict"] in ("confirm", "reject", "wrong_category") and r["label"]]
    missed = [{"clause_text": r["clause_text"], "category": r["correct_category"] or r["case_category"], "comment": r["comment"], "source": r["source"],
               "review_id": r["review_id"]} for r in rows if r["verdict"] == "missed"]
    comments = [{"finding_label": r["label"], "comment": r["comment"], "clause_text": r["clause_text"], "review_id": r["review_id"]}
                for r in rows if r["comment"]]
    corr = [{"label": json.loads(e["labels"] or "[]"), "category": json.loads(e["categories"] or "[]"), "original": e["original_text"], "proposed": e["proposed_text"],
             "accepted": e["new_text"], "method": e["method"], "resolved": e["resolved"], "review_id": e["review_id"]}
            for e in conn.execute("SELECT * FROM edits WHERE COALESCE(user_id,'') NOT LIKE 'claude-test%'").fetchall()]
    files = {"finding_feedback.jsonl": ff, "missed.jsonl": missed, "corrections.jsonl": corr, "comments.jsonl": comments}
    for name, data in files.items():
        (out / name).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in data), encoding="utf-8")
    manifest = {"created": _stamp(), "counts": {k: len(v) for k, v in files.items()},
                "finding_feedback_by_verdict": {v: sum(1 for x in ff if x["verdict"] == v) for v in ("confirm", "reject", "wrong_category")},
                "corrections_resolved": sum(1 for c in corr if c["resolved"]), "by_source": {s: sum(1 for x in ff if x["source"] == s) for s in {x["source"] for x in ff}}}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("training export %s: %s", out, manifest["counts"]); return out, manifest


def seed_gold(conn):
    """Turn the gold suite into feedback rows (source=gold_suite): findings matching a reviewer correction → confirm,
    flagged findings on corrected documents → reject, uncovered mandatory corrections → missed. Idempotent."""
    import sys; sys.path.insert(0, str(ROOT))
    import eval_case as ev
    from . import store
    conn.execute("DELETE FROM feedback WHERE source='gold_suite'")
    n = {"confirm": 0, "reject": 0, "missed": 0}
    for name, g in ev.GOLD["documents"].items():
        path = ev.CASE_DIR / name if (ev.CASE_DIR / name).exists() else Path(ROOT / "kb" / "gold" / name)
        doc, fs = ev.review(path)
        rid = "GOLD_" + Path(name).stem
        store.save_review(conn, {"review_id": rid, "source": name, "findings": fs, "n_clauses": len(doc["clauses"]),
                                 "conclusion": {"document": {"contract_kind": doc["fields"].get("contract_kind"), "subject": doc["fields"].get("subject")}}})
        if g["expected"]:
            used = set()
            for e in g["expected"]:
                hit = None
                for f in fs:
                    if f.get("case_category") != e["category"]: continue
                    hay = ev.norm(f.get("clause_text")) + " " + ev.norm(" ".join(map(str, f.get("matched") or []))) + " " + ev.norm(f.get("explanation"))
                    if any(ev.norm(a) in hay for a in e["anchors"]): hit = f; break
                if hit:
                    store.add_feedback(conn, rid, "confirm", finding=hit, comment=f"gold {e['id']}: {e['what']}", user_id="gold", source="gold_suite"); n["confirm"] += 1; used.add(hit["finding_id"])
                elif e["must"]:
                    store.add_feedback(conn, rid, "missed", clause_text=e["what"], correct_category=e["category"], comment=f"gold {e['id']}", user_id="gold", source="gold_suite"); n["missed"] += 1
        else:
            for f in fs:
                if f["severity"] in ("ERROR", "RISK") and f["disposition"] == "FLAGGED":
                    store.add_feedback(conn, rid, "reject", finding=f, comment="flagged on a reviewer-corrected document", user_id="gold", source="gold_suite"); n["reject"] += 1
    conn.commit(); log.info("gold seed: %s", n); return n


def _gold_scores():
    import subprocess, sys
    out = subprocess.run([sys.executable, str(ROOT / "eval_case.py")], capture_output=True, text=True, cwd=str(ROOT), timeout=900).stdout
    m = re.search(r"RECALL must: (\d+)/(\d+)\s+optional: (\d+)/(\d+)\s+FALSE POSITIVES on corrected docs: (\d+)", out)
    k = re.search(r"MUST NOT DOWNGRADED BY FILTER: (\d+)/", out)
    return {"must": int(m.group(1)), "must_total": int(m.group(2)), "fp": int(m.group(5)), "kept": int(k.group(1)) if k else None} if m else None


def retrain(conn):
    """Train the finding-acceptance filter from feedback, gate it on the gold suite, promote or reject, register."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    import joblib
    out, manifest = export(conn)
    data = [json.loads(l) for l in (out / "finding_feedback.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    X = [d["text"] for d in data]; y = [d["y"] for d in data]
    n_pos, n_neg = sum(y), len(y) - sum(y)
    mid = "finding-filter-" + _stamp()
    reg = lambda status, metrics, notes, gold=None: (conn.execute(
        "INSERT INTO model_registry(model_id, kind, path, trained_at, n_train, metrics, gold_must, gold_fp, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (mid, "finding-filter", str(FILTER_DIR / f"{mid}.joblib"), _stamp(), len(y), json.dumps(metrics, ensure_ascii=False),
         f"{gold['must']}/{gold['must_total']}" if gold else None, gold["fp"] if gold else None, status, notes)), conn.commit())
    if len(y) < MIN_EXAMPLES or min(n_pos, n_neg) < MIN_PER_CLASS:
        note = f"not enough feedback: {len(y)} examples ({n_pos} confirm / {n_neg} reject); need ≥{MIN_EXAMPLES} and ≥{MIN_PER_CLASS} per class"
        reg("skipped", {"n": len(y), "confirm": n_pos, "reject": n_neg}, note); log.info(note)
        return {"status": "skipped", "reason": note, "dataset": str(out), "manifest": manifest}
    pipe = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True), LogisticRegression(max_iter=2000, class_weight="balanced"))
    folds = min(5, min(n_pos, n_neg))
    cv = cross_val_score(pipe, X, y, cv=StratifiedKFold(folds, shuffle=True, random_state=7), scoring="f1_macro")
    pipe.fit(X, y)
    FILTER_DIR.mkdir(parents=True, exist_ok=True); cand = FILTER_DIR / f"{mid}.joblib"; joblib.dump(pipe, cand)
    metrics = {"cv_macro_f1": round(float(cv.mean()), 3), "cv_folds": folds, "n": len(y), "confirm": n_pos, "reject": n_neg}
    base = _gold_scores()
    active = FILTER_DIR / "active.joblib"; backup = FILTER_DIR / "active.prev.joblib"
    if active.exists(): shutil.copy(active, backup)
    shutil.copy(cand, active)
    new = _gold_scores()
    ok = bool(new and base and new["must"] >= base["must"] and new["fp"] <= base["fp"] and (new["kept"] or 0) >= (base["kept"] or 0))
    if not ok:
        if backup.exists(): shutil.copy(backup, active)
        else: active.unlink(missing_ok=True)
    reg("promoted" if ok else "rejected", metrics, f"gold before {base} after {new}", new)
    log.info("finding-filter %s: %s %s", mid, "PROMOTED" if ok else "REJECTED by gate", metrics)
    return {"status": "promoted" if ok else "rejected", "model_id": mid, "metrics": metrics, "gold_before": base, "gold_after": new, "dataset": str(out), "manifest": manifest}


_filter = None


def apply_filter(findings):
    """At review time: downgrade FLAGGED findings that the promoted filter predicts reviewers reject. Never removes."""
    global _filter
    active = FILTER_DIR / "active.joblib"
    if not active.exists(): return findings
    try:
        if _filter is None or _filter[0] != active.stat().st_mtime:
            import joblib; _filter = (active.stat().st_mtime, joblib.load(active))
        model = _filter[1]
        cand = [f for f in findings if f["disposition"] == "FLAGGED"]
        if not cand: return findings
        probs = model.predict_proba([_text(f["label"], f.get("case_category"), f.get("clause_text")) for f in cand])
        idx = list(model.classes_).index(0)
        for f, p in zip(cand, probs):
            if p[idx] >= REJECT_THRESHOLD:
                f["disposition"] = "INSUFFICIENT_EVIDENCE"; f["filter_p_reject"] = round(float(p[idx]), 3)
                f["explanation"] += f" [По истории отзывов похожие замечания часто отклонялись (p={p[idx]:.2f}); требует проверки.]"
    except Exception as ex:  # noqa
        log.warning("finding filter failed: %s", ex)
    return findings
