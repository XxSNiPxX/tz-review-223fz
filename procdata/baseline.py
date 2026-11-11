"""Tier 2 baselines (TF-IDF + linear SVM) trained on what the knowledge base has today.

Labels available now are WEAK (regex-derived): fas_findings.requirement_type and per-argument outcome, and the
tier-1 check labels over corpus clauses. They give a working classifier and an honest number to beat once the
expert annotations (annotations table / annotation_*.jsonl) exist. Split is by procurement notice to avoid leakage.
"""
import json, numpy as np
from pathlib import Path
from .common import ROOT, log

OUT = ROOT / "models" / "baselines"


def _split_by_group(groups, test_frac=0.25, seed=13):
    rng = np.random.default_rng(seed)
    uniq = sorted(set(groups)); rng.shuffle(uniq)
    test = set(uniq[: max(1, int(len(uniq) * test_frac))])
    return np.array([g not in test for g in groups]), np.array([g in test for g in groups])


def train_requirement_type(db):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.svm import LinearSVC
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import classification_report
    import joblib
    rows = db.execute("SELECT COALESCE(challenged_text,'') || ' ' || COALESCE(complainant_argument,'') AS text, requirement_type, "
                      "COALESCE(procurement_notice_id, case_id, doc_uuid) AS grp FROM fas_findings WHERE requirement_type != 'OTHER' "
                      "AND length(COALESCE(challenged_text,'') || COALESCE(complainant_argument,'')) > 40").fetchall()
    if len(rows) < 40: log.warning("too few rows (%d)", len(rows)); return
    X = [r["text"] for r in rows]; y = [r["requirement_type"] for r in rows]; g = [r["grp"] for r in rows]
    tr, te = _split_by_group(g)
    pipe = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=50000), LinearSVC(C=0.5, class_weight="balanced"))
    pipe.fit([x for x, m in zip(X, tr) if m], [v for v, m in zip(y, tr) if m])
    pred = pipe.predict([x for x, m in zip(X, te) if m])
    rep = classification_report([v for v, m in zip(y, te) if m], pred, zero_division=0)
    log.info("requirement_type baseline (weak labels, %d train / %d test, split by notice):\n%s", tr.sum(), te.sum(), rep)
    OUT.mkdir(parents=True, exist_ok=True); joblib.dump(pipe, OUT / "requirement_type.joblib")
    (OUT / "requirement_type.report.txt").write_text(rep)


def train_outcome(db):
    """Does the complaint argument text predict FAS outcome? Expected to be weak: outcome depends on evidence, not wording."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import classification_report
    import joblib
    rows = db.execute("SELECT COALESCE(challenged_text,'') || ' ' || COALESCE(complainant_argument,'') AS text, outcome, "
                      "COALESCE(procurement_notice_id, case_id) AS grp FROM fas_findings WHERE outcome IN ('UPHELD','DISMISSED') "
                      "AND length(COALESCE(challenged_text,'') || COALESCE(complainant_argument,'')) > 40").fetchall()
    X = [r["text"] for r in rows]; y = [r["outcome"] for r in rows]; g = [r["grp"] for r in rows]
    tr, te = _split_by_group(g)
    pipe = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True), LogisticRegression(max_iter=2000, class_weight="balanced"))
    pipe.fit([x for x, m in zip(X, tr) if m], [v for v, m in zip(y, tr) if m])
    pred = pipe.predict([x for x, m in zip(X, te) if m])
    rep = classification_report([v for v, m in zip(y, te) if m], pred, zero_division=0)
    log.info("outcome-from-argument baseline (%d train / %d test):\n%s", tr.sum(), te.sum(), rep)
    OUT.mkdir(parents=True, exist_ok=True); joblib.dump(pipe, OUT / "outcome.joblib"); (OUT / "outcome.report.txt").write_text(rep)


def run(db):
    train_requirement_type(db)
    train_outcome(db)
