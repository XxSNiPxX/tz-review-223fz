"""Persistence for the feedback loop: every review, every finding shown, every reviewer verdict/comment/missed issue.
Edits live in the `edits` table (server.py). All writes are idempotent per review (findings of a re-check supersede
the previous ones but are kept, so the history of what the system said is preserved)."""
import datetime, hashlib, json, uuid
from pathlib import Path

ENGINE_VERSION = "2026.11.13"


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def sha256(path):
    try:
        h = hashlib.sha256(Path(path).read_bytes()).hexdigest(); return h
    except Exception:  # noqa
        return None


def save_review(conn, report, upload_path=None):
    con = report.get("conclusion") or {}; d = con.get("document") or {}
    rid = report["review_id"]; now = _now()
    conn.execute("""INSERT INTO reviews(review_id, source, file_sha256, upload_path, contract_kind, subject, n_clauses, n_findings, errors, risks, manual,
                    verdict, llm_used, engine_version, kb_rules, kb_findings, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(review_id) DO UPDATE SET n_findings=excluded.n_findings, errors=excluded.errors, risks=excluded.risks, manual=excluded.manual,
                    verdict=excluded.verdict, llm_used=excluded.llm_used, n_clauses=excluded.n_clauses, updated_at=excluded.updated_at,
                    upload_path=COALESCE(excluded.upload_path, reviews.upload_path), file_sha256=COALESCE(excluded.file_sha256, reviews.file_sha256)""",
                 (rid, report.get("source"), sha256(upload_path) if upload_path else None, upload_path, d.get("contract_kind"), d.get("subject"),
                  report.get("n_clauses"), len(report["findings"]), con.get("errors"), con.get("risks"), con.get("manual_review"), con.get("verdict"),
                  int(bool(report.get("llm_used"))), ENGINE_VERSION, (report.get("kb_release") or {}).get("legal_rules"),
                  (report.get("kb_release") or {}).get("fas_findings"), now, now))
    conn.execute("UPDATE review_findings SET superseded=1 WHERE review_id=? AND superseded=0", (rid,))
    for f in report["findings"]:
        conn.execute("""INSERT OR REPLACE INTO review_findings(finding_id, review_id, clause_id, anchor, label, case_category, analysis_type, severity, disposition,
                        confidence, method, clause_text, explanation, proposed_text, evidence_ids, scope_method, created_at, superseded)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                     (f["finding_id"], rid, f.get("clause_id"), (f.get("anchors") or [None])[0], f["label"], f.get("case_category"), f.get("analysis_type"),
                      f["severity"], f["disposition"], f.get("confidence"), f.get("method"), f.get("clause_text"), f.get("explanation"), f.get("proposed_text"),
                      json.dumps([o["id"] for o in f.get("evidence_objects", [])], ensure_ascii=False), f.get("scope_method"), now))
    conn.commit()


def add_feedback(conn, review_id, verdict, finding=None, clause_id=None, clause_text=None, correct_category=None, comment=None, user_id=None, source="ui"):
    fid = "FB" + uuid.uuid4().hex[:10]
    conn.execute("""INSERT INTO feedback(feedback_id, review_id, finding_id, clause_id, label, case_category, verdict, correct_category, comment, clause_text, user_id, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (fid, review_id, finding and finding.get("finding_id"), clause_id or (finding and finding.get("clause_id")), finding and finding.get("label"),
                  finding and finding.get("case_category"), verdict, correct_category, comment, clause_text or (finding and finding.get("clause_text")), user_id, source))
    conn.commit(); return fid


def feedback_for(conn, review_id):
    return [dict(r) for r in conn.execute("SELECT * FROM feedback WHERE review_id=? ORDER BY created_at", (review_id,)).fetchall()]


def stats(conn):
    q = lambda s: conn.execute(s).fetchone()[0]
    return {"reviews": q("SELECT COUNT(*) FROM reviews"), "findings_shown": q("SELECT COUNT(*) FROM review_findings"),
            "feedback": q("SELECT COUNT(*) FROM feedback"), "edits": q("SELECT COUNT(*) FROM edits"),
            "by_verdict": dict(conn.execute("SELECT verdict, COUNT(*) FROM feedback GROUP BY 1").fetchall()),
            "models": [dict(r) for r in conn.execute("SELECT model_id, kind, trained_at, n_train, status, gold_must, gold_fp FROM model_registry ORDER BY trained_at DESC LIMIT 10").fetchall()]}
