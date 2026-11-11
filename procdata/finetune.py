"""Fine-tune a small Russian BERT (cointegrated/rubert-tiny2, 29M params) as a clause-role classifier on CPU.

Task: TECHNICAL (requirement about the object) | CONTRACT (contract / procedure text) | LEGAL (citations, boilerplate).
This is the scoping decision that gates every other check, i.e. the main source of false positives.
Labels: current heuristic (checks.clause_scope) over corpus clauses + FAS-challenged clauses forced to TECHNICAL.
Split by procurement. Reports accuracy / per-class F1 on held-out procurements and agreement with the heuristic.
Outputs models/clause-role/ (weights + label map + metrics.json).
"""
import json, random, time, sqlite3
from pathlib import Path
import numpy as np
from .common import ROOT, log
from . import checks

BASE = ROOT / "models" / "rubert-tiny2"
OUT = ROOT / "models" / "clause-role"
LABELS = ["TECHNICAL", "CONTRACT", "LEGAL"]


def build_dataset(db, per_class=6000, seed=7):
    rows = db.execute("SELECT c.clause_id, c.procurement_id, c.clause_text, d.original_filename FROM clauses c JOIN documents d ON d.document_id=c.document_id "
                      "WHERE length(c.clause_text) BETWEEN 40 AND 1200").fetchall()
    by = {l: [] for l in LABELS}
    for r in rows:
        c = {"clause_text": r["clause_text"], "document_name": r["original_filename"] or ""}
        by[checks.clause_scope(c)].append((r["procurement_id"], r["clause_text"], checks.clause_scope(c)))
    # requirements that FAS actually ruled on are technical by definition: strong positives from a different source
    for r in db.execute("SELECT COALESCE(procurement_notice_id, case_id) AS p, challenged_text FROM fas_findings WHERE challenged_text IS NOT NULL AND length(challenged_text) BETWEEN 40 AND 1200"):
        by["TECHNICAL"].append((f"FAS:{r['p']}", r["challenged_text"], "TECHNICAL"))
    rng = random.Random(seed)
    data = []
    for l in LABELS:
        rng.shuffle(by[l]); data += by[l][:per_class]
    procs = sorted({p for p, _, _ in data}); rng.shuffle(procs)
    test_p = set(procs[: max(1, len(procs) // 5)])
    train = [(t, l) for p, t, l in data if p not in test_p]
    test = [(t, l) for p, t, l in data if p in test_p]
    log.info("dataset: %d train / %d test clauses from %d procurements (%d held out); class sizes %s",
             len(train), len(test), len(procs), len(test_p), {l: len(by[l]) for l in LABELS})
    return train, test


def train(db, epochs=2, batch=32, max_len=128, lr=5e-5, per_class=6000):
    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    torch.set_num_threads(max(4, (torch.get_num_threads() or 8)))
    tok = AutoTokenizer.from_pretrained(str(BASE))
    model = AutoModelForSequenceClassification.from_pretrained(str(BASE), num_labels=len(LABELS))
    tr, te = build_dataset(db, per_class=per_class)
    lab2id = {l: i for i, l in enumerate(LABELS)}

    def collate(b):
        enc = tok([t for t, _ in b], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
        enc["labels"] = torch.tensor([lab2id[l] for _, l in b]); return enc
    dl = DataLoader(tr, batch_size=batch, shuffle=True, collate_fn=collate)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * len(dl); sched = torch.optim.lr_scheduler.LinearLR(opt, 1.0, 0.05, total_iters=steps)
    t0 = time.time(); model.train(); step = 0
    for ep in range(epochs):
        for b in dl:
            out = model(**b); out.loss.backward(); opt.step(); sched.step(); opt.zero_grad(); step += 1
            if step % 50 == 0: log.info("epoch %d step %d/%d loss %.4f  %.0fs", ep + 1, step, steps, out.loss.item(), time.time() - t0)
    metrics = evaluate(model, tok, te, max_len)
    metrics.update({"base_model": "cointegrated/rubert-tiny2", "params": sum(p.numel() for p in model.parameters()), "epochs": epochs, "batch": batch,
                    "max_len": max_len, "lr": lr, "train_size": len(tr), "test_size": len(te), "train_seconds": round(time.time() - t0), "labels": LABELS,
                    "label_source": "heuristic clause_scope + FAS-challenged clauses (weak labels)", "split": "by procurement"})
    OUT.mkdir(parents=True, exist_ok=True); model.save_pretrained(str(OUT)); tok.save_pretrained(str(OUT))
    (OUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("saved %s\n%s", OUT, json.dumps(metrics, ensure_ascii=False, indent=1))
    return metrics


def evaluate(model, tok, te, max_len=128):
    import torch
    from sklearn.metrics import classification_report, confusion_matrix
    model.eval(); preds = []
    with torch.no_grad():
        for i in range(0, len(te), 64):
            enc = tok([t for t, _ in te[i:i + 64]], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
            preds += model(**enc).logits.argmax(-1).tolist()
    y = [LABELS.index(l) for _, l in te]
    rep = classification_report(y, preds, target_names=LABELS, output_dict=True, zero_division=0)
    cm = confusion_matrix(y, preds).tolist()
    return {"accuracy": round(rep["accuracy"], 4), "macro_f1": round(rep["macro avg"]["f1-score"], 4),
            "per_class": {l: {k: round(v, 3) for k, v in rep[l].items()} for l in LABELS}, "confusion": cm}


class ClauseRole:
    """Inference wrapper used by the engine when models/clause-role exists."""
    def __init__(self):
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch
        self.tok = AutoTokenizer.from_pretrained(str(OUT)); self.model = AutoModelForSequenceClassification.from_pretrained(str(OUT)).eval()
        self.torch = torch

    def predict(self, texts, max_len=128):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), 64):
                enc = self.tok(texts[i:i + 64], truncation=True, max_length=max_len, padding=True, return_tensors="pt")
                probs = self.model(**enc).logits.softmax(-1)
                for p in probs: out.append((LABELS[int(p.argmax())], float(p.max())))
        return out


def available():
    return (OUT / "config.json").exists()
