"""Local retrieval index: embeddings of legal rule parts, FAS precedents (challenged text + reasoning) and corpus
clauses, stored as numpy arrays next to the database. CPU model: intfloat/multilingual-e5-small from models/.
"""
import json, numpy as np
from pathlib import Path
from .common import ROOT, log

MODEL_DIR = ROOT / "models" / "multilingual-e5-small"
IDX_DIR = ROOT / "data" / "index"
_model = None


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(str(MODEL_DIR) if MODEL_DIR.exists() else "intfloat/multilingual-e5-small", device="cpu")
    return _model


def embed(texts, prefix="passage: "):
    return model().encode([prefix + t[:1500] for t in texts], batch_size=32, normalize_embeddings=True, show_progress_bar=False)


def build(db):
    IDX_DIR.mkdir(parents=True, exist_ok=True)
    sets = {
        "rules": ("SELECT rule_id AS id, law || ' ст.' || article || COALESCE(' ч.' || part, '') || ': ' || substr(rule_text, 1, 1200) AS text, "
                  "json_object('law', law, 'article', article, 'part', part, 'source', source, 'category', rule_category) AS meta "
                  "FROM legal_rules WHERE rule_category NOT LIKE '%other_edition%' AND part IS NOT NULL"),
        "precedents": ("SELECT finding_id AS id, COALESCE(challenged_text, '') || ' || ' || COALESCE(complainant_argument, '') || ' || ' || COALESCE(fas_reasoning, '') AS text, "
                       "json_object('case_id', case_id, 'doc_uuid', doc_uuid, 'notice', procurement_notice_id, 'outcome', outcome, 'requirement_type', requirement_type, "
                       "'legal_provision', legal_provision, 'review_status', review_status) AS meta FROM fas_findings WHERE length(COALESCE(challenged_text,'') || COALESCE(complainant_argument,'')) > 40"),
    }
    for name, sql in sets.items():
        rows = db.execute(sql).fetchall()
        if not rows: log.warning("%s: nothing to index", name); continue
        vecs = embed([r["text"] for r in rows])
        np.save(IDX_DIR / f"{name}.npy", vecs.astype(np.float32))
        (IDX_DIR / f"{name}.jsonl").write_text("\n".join(json.dumps({"id": r["id"], "text": r["text"][:800], "meta": json.loads(r["meta"])}, ensure_ascii=False) for r in rows), encoding="utf-8")
        log.info("index %s: %d vectors", name, len(rows))


class Index:
    def __init__(self, name):
        self.vecs = np.load(IDX_DIR / f"{name}.npy")
        self.rows = [json.loads(l) for l in (IDX_DIR / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()]

    def search(self, query, k=5, filt=None):
        q = embed([query], prefix="query: ")[0]
        sims = self.vecs @ q
        order = np.argsort(-sims)
        out = []
        for i in order:
            r = self.rows[i]
            if filt and not filt(r): continue
            out.append({**r, "score": float(sims[i])})
            if len(out) >= k: break
        return out
