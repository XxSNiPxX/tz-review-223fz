#!/usr/bin/env python3
"""HTTP server for the review engine. No outbound network: it only reads the local knowledge base and models.

  uvicorn server:app --host 0.0.0.0 --port 8000      (or: python server.py)

API
  POST /api/reviews            multipart: file=<ТЗ .docx/.pdf/.xlsx>  [use_llm=true|false]  -> {review_id, status}
  POST /api/reviews/by-notice  json: {"notice": "32615808789", "use_llm": false}            -> {review_id, status}
  GET  /api/reviews            list
  GET  /api/reviews/{id}       status + report when done
  GET  /api/kb                 knowledge-base counts and model availability
  GET  /api/procurements?q=    procurements in the KB that have extracted clauses
  GET  /api/rules/{rule_id}    rule text
  GET  /api/precedents/{finding_id}
  GET  /                       web UI
"""
import json, os, re, threading, uuid, datetime, shutil, logging
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from procdata.common import load_config, open_db, ROOT, log
from procdata import checks, explain, index as kb_index, ingest, report as rep
import review as rv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
app = FastAPI(title="223-ФЗ ТЗ review", version="0.1")
CFG = load_config()
UPLOADS = ROOT / "data" / "uploads"; UPLOADS.mkdir(parents=True, exist_ok=True)
REVIEWS = ROOT / "data" / "reviews"; REVIEWS.mkdir(parents=True, exist_ok=True)
JOBS = {}           # review_id -> {status, source, started, error, report_path}
LOCK = threading.Lock()


def _load_jobs():
    """Reports persist as JSON; rebuild the job list from them so restarts/reloads keep history."""
    for p in sorted(REVIEWS.glob("R*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            JOBS[r["review_id"]] = {"review_id": r["review_id"], "status": "done", "source": r["source"], "use_llm": r.get("llm_used", False),
                                    "started": r["reviewed_at"], "finished": r["reviewed_at"], "report_path": str(p), "summary": r["summary"]}
        except Exception as ex:  # noqa
            log.warning("skip %s: %s", p.name, ex)


_load_jobs()
_idx = {}


def db():
    return open_db(CFG)


def indexes():
    if "rules" not in _idx:
        try:
            _idx["rules"], _idx["prec"] = kb_index.Index("rules"), kb_index.Index("precedents")
        except Exception as ex:  # noqa
            log.warning("index unavailable: %s", ex); _idx["rules"] = _idx["prec"] = None
    return _idx["rules"], _idx["prec"]


def run_review(review_id, clauses, source, use_llm, doc=None):
    try:
        conn = db()
        findings = rv.analyze(clauses, doc)
        rules_idx, prec_idx = indexes()
        llm_on = use_llm and explain.available() and os.environ.get("REVIEW_USE_LLM", "1") not in ("0", "false", "no")
        for f in findings:
            f["evidence_objects"] = rv.resolve_evidence(conn, f["evidence"], rules_idx, prec_idx, f["clause_text"], f["analysis_type"], f["label"])
            if llm_on and explain.wants_llm(f): explain.explain(f, f["evidence_objects"])
        by = {}
        for f in findings: by.setdefault(f["analysis_type"], []).append(f)
        scopes = {}
        for c in clauses: scopes[c.get("scope", "?")] = scopes.get(c.get("scope", "?"), 0) + 1
        report = {"review_id": review_id, "source": source, "reviewed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                  "llm_used": llm_on, "n_clauses": len(clauses), "clause_scopes": scopes,
                  "kb_release": {"legal_rules": conn.execute("SELECT COUNT(*) FROM legal_rules").fetchone()[0],
                                 "fas_findings": conn.execute("SELECT COUNT(*) FROM fas_findings").fetchone()[0]},
                  "summary": {k: {"findings": len(v), "errors": sum(x["severity"] == "ERROR" for x in v), "risks": sum(x["severity"] == "RISK" for x in v)} for k, v in by.items()},
                  "conclusion": rv.conclusion(findings, doc), "document_view": rep.document_view(doc, clauses), "findings": findings}
        path = REVIEWS / f"{review_id}.json"; path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        with LOCK: JOBS[review_id].update(status="done", report_path=str(path), finished=datetime.datetime.now().isoformat(timespec="seconds"), summary=report["summary"])
    except Exception as ex:  # noqa
        log.exception("review failed")
        with LOCK: JOBS[review_id].update(status="error", error=str(ex)[:300])


def start(clauses, source, use_llm, doc=None):
    rid = "R" + uuid.uuid4().hex[:10]
    with LOCK: JOBS[rid] = {"review_id": rid, "status": "running", "source": source, "use_llm": use_llm, "started": datetime.datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=run_review, args=(rid, clauses, source, use_llm, doc), daemon=True).start()
    return rid


@app.post("/api/reviews")
async def create_review(file: UploadFile = File(...), use_llm: bool = Form(False)):
    dest = UPLOADS / (uuid.uuid4().hex[:8] + "_" + re.sub(r"[^\w.\-]", "_", file.filename or "upload")[:120])
    with open(dest, "wb") as f: shutil.copyfileobj(file.file, f)
    try:
        path = rv.prepare_file(dest)                       # real type via file(1); DOC/RTF/XLS converted; archives rejected
    except rv.UnreadableFile as ex:
        raise HTTPException(422, str(ex))
    doc = None
    try:
        doc = ingest.parse(path); clauses = doc["clauses"]
    except Exception as ex:  # noqa  damaged or unusual file: flat text fallback, never a 500
        log.warning("structured ingest failed for %s: %s", file.filename, ex)
        try:
            clauses = rv.clauses_from_file(path)
        except Exception as ex2:  # noqa
            raise HTTPException(422, f"файл поврежден или не читается ({type(ex2).__name__})")
    if not clauses: raise HTTPException(422, "текст не извлечен: пустой документ или скан без текстового слоя")
    for c in clauses: c["document_name"] = file.filename
    return {"review_id": start(clauses, file.filename, use_llm, doc), "status": "running", "n_clauses": len(clauses)}


class ByNotice(BaseModel):
    notice: str
    use_llm: bool = False


@app.post("/api/reviews/by-notice")
def review_by_notice(body: ByNotice):
    clauses = rv.clauses_from_db(db(), body.notice)
    if not clauses: raise HTTPException(404, "no extracted clauses for this notice in the knowledge base")
    return {"review_id": start(clauses, f"EIS223:{body.notice}", body.use_llm), "status": "running", "n_clauses": len(clauses)}


@app.get("/api/reviews")
def list_reviews():
    return sorted(JOBS.values(), key=lambda j: j["started"], reverse=True)


@app.get("/api/reviews/{rid}")
def get_review(rid: str):
    j = JOBS.get(rid)
    if not j: raise HTTPException(404, "unknown review")
    if j["status"] != "done": return j
    return {**j, "report": json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))}


@app.get("/api/reviews/{rid}/report.{fmt}")
def download_report(rid: str, fmt: str):
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "report not ready")
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    base = re.sub(r"[^\w.-]", "_", Path(report["source"]).stem)[:60]
    if fmt == "json":
        return FileResponse(j["report_path"], media_type="application/json", filename=f"review_{base}.json")
    if fmt == "html":
        p = REVIEWS / f"{rid}.html"; p.write_text(rep.render_html(report), encoding="utf-8")
        return FileResponse(str(p), media_type="text/html", filename=f"review_{base}.html")
    if fmt == "docx":
        p = REVIEWS / f"{rid}.docx"; rep.render_docx(report, p)
        return FileResponse(str(p), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=f"review_{base}.docx")
    raise HTTPException(400, "fmt must be json, html or docx")


@app.get("/api/kb")
def kb():
    conn = db()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("procurements", "documents", "clauses", "legal_rules", "law_texts", "fas_cases", "fas_documents", "fas_findings")}
    r, p = indexes()
    return {"counts": counts, "retrieval_index": bool(r), "llm_available": explain.available(), "lexicon_terms": len(checks.LEX["vague_terms"]),
            "linked_procurements": conn.execute("SELECT COUNT(DISTINCT p.procurement_id) FROM procurements p JOIN clauses c ON c.procurement_id=p.procurement_id JOIN fas_findings f ON f.procurement_notice_id=p.eis_id").fetchone()[0]}


@app.get("/api/procurements")
def procurements(q: str = ""):
    conn = db()
    rows = conn.execute("""SELECT p.eis_id, p.name, p.customer_name, p.initial_price, COUNT(c.clause_id) n_clauses,
                           (SELECT COUNT(*) FROM fas_findings f WHERE f.procurement_notice_id=p.eis_id) n_fas
                           FROM procurements p JOIN clauses c ON c.procurement_id=p.procurement_id
                           WHERE p.name LIKE ? OR p.eis_id LIKE ? GROUP BY 1 ORDER BY n_fas DESC, n_clauses DESC LIMIT 100""", (f"%{q}%", f"%{q}%")).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/rules/{rule_id}")
def rule(rule_id: str):
    r = db().execute("SELECT * FROM legal_rules WHERE rule_id=?", (rule_id,)).fetchone()
    if not r: raise HTTPException(404)
    return dict(r)


@app.get("/api/precedents/{finding_id}")
def precedent(finding_id: str):
    r = db().execute("SELECT f.*, d.source_url AS decision_url FROM fas_findings f LEFT JOIN fas_documents d ON d.doc_uuid=f.doc_uuid WHERE f.finding_id=?", (finding_id,)).fetchone()
    if not r: raise HTTPException(404)
    return dict(r)


app.mount("/static", StaticFiles(directory=str(ROOT / "web")), name="static")


@app.get("/")
def index():
    return FileResponse(str(ROOT / "web" / "index.html"), headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
