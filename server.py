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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from procdata.common import load_config, open_db, ROOT, log
from procdata import checks, explain, index as kb_index, ingest, report as rep, annotate, edits as ed, store, training, auth, autofix
import review as rv

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
app = FastAPI(title="223-ФЗ ТЗ review", version="0.1")

_BASIC = os.environ.get("REVIEW_BASIC_AUTH", "").strip()
if _BASIC:
    import base64, secrets
    from starlette.responses import Response
    _EXPECTED = "Basic " + base64.b64encode(_BASIC.encode()).decode()

    @app.middleware("http")
    async def _basic_auth(request, call_next):
        got = request.headers.get("authorization", "")
        if request.url.path != "/api/health" and not secrets.compare_digest(got, _EXPECTED):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="TZ review"'})
        return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- login (Yandex ID / Google)
PUBLIC_PATHS = ("/login", "/auth/", "/static/", "/api/health", "/api/auth/")


@app.middleware("http")
async def _require_login(request, call_next):
    if auth.required() and not request.url.path.startswith(PUBLIC_PATHS) and not request.session.get("user"):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "требуется вход"}, status_code=401)
        return RedirectResponse("/login?next=" + request.url.path)
    return await call_next(request)


_secret = os.environ.get("SESSION_SECRET") or ("dev-" + uuid.uuid4().hex)
if auth.required() and not os.environ.get("SESSION_SECRET"):
    log.warning("SESSION_SECRET not set: sessions reset on every restart")
app.add_middleware(SessionMiddleware, secret_key=_secret, session_cookie="tz_session", max_age=14 * 24 * 3600,
                   same_site="lax", https_only=os.environ.get("AUTH_PUBLIC_URL", "").startswith("https"))


@app.get("/login")
def login_page():
    return FileResponse(str(ROOT / "web" / "login.html"), headers={"Cache-Control": "no-cache"})


@app.get("/api/auth/providers")
def auth_providers():
    return {"providers": [{"id": p, "name": auth.PROVIDERS[p]["name"]} for p in auth.enabled_providers()], "required": auth.required(),
            "demo": auth.demo_enabled(), "all": [{"id": p, "name": auth.PROVIDERS[p]["name"]} for p in auth.PROVIDERS],
            "restricted": bool(os.environ.get("AUTH_ALLOWED_EMAILS") or os.environ.get("AUTH_ALLOWED_DOMAINS"))}


@app.post("/auth/demo")
async def auth_demo(request: Request):
    if not auth.demo_enabled(): raise HTTPException(404, "demo login disabled")
    form = await request.form()
    request.session["user"] = auth.demo_user(form.get("name"))
    return RedirectResponse("/", status_code=303)


@app.get("/auth/{provider}")
def auth_start(provider: str, request: Request):
    if provider not in auth.enabled_providers(): raise HTTPException(404, "provider not configured")
    return RedirectResponse(auth.authorize_redirect(request, provider))


@app.get("/auth/{provider}/callback")
def auth_callback(provider: str, request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code: return RedirectResponse("/login?error=" + (error or "cancelled"))
    user, err = auth.finish(request, provider, code, state)
    if err: return RedirectResponse("/login?error=" + err)
    request.session["user"] = user
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request):
    request.session.clear(); return RedirectResponse("/login" if auth.required() else "/")


@app.get("/api/me")
def me(request: Request):
    return {"user": request.session.get("user"), "required": auth.required()}


def _uid(request):
    u = request.session.get("user") if request is not None else None
    return u and (u.get("email") or u.get("id"))
CFG = load_config()
UPLOADS = ROOT / "data" / "uploads"; UPLOADS.mkdir(parents=True, exist_ok=True)
REVIEWS = ROOT / "data" / "reviews"; REVIEWS.mkdir(parents=True, exist_ok=True)
JOBS = {}           # review_id -> {status, source, started, error, report_path}
LOCK = threading.Lock()
LLM_JOBS = threading.Lock()           # LLM phases run strictly one at a time (see explain.LLM_LOCK); rule phases stay parallel


def _load_jobs():
    """Reports persist as JSON; rebuild the job list from them so restarts/reloads keep history."""
    seen = {}
    for p in sorted(REVIEWS.glob("R*.json")):
        if not re.fullmatch(r"R[0-9a-f]{10}(\.v2)?\.json", p.name): continue        # skip working copies (.doc.json) and exports
        rid = p.name.split(".")[0]
        if rid in seen and not p.name.endswith(".v2.json"): continue
        seen[rid] = p
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
            up = r.get("upload_path")
            JOBS[rid] = {"legacy": not r.get("document_view"),"review_id": r["review_id"], "status": "done", "source": r["source"], "use_llm": r.get("llm_used", False),
                                    "started": r["reviewed_at"], "finished": r["reviewed_at"], "report_path": str(p), "summary": r["summary"],
                                    "llm_status": ("interrupted" if r.get("llm_status") in ("pending", "running") else r.get("llm_status", "off")), "upload_path": up, "upload_is_docx": bool(up and up.lower().endswith(".docx"))}
        except Exception as ex:  # noqa
            log.warning("skip %s: %s", p.name, ex)


_load_jobs()


def _auto_retrain_loop():
    """Every 30 min: if at least 10 new reviewer verdicts arrived since the last training run, retrain behind the gold gate."""
    import time
    while True:
        time.sleep(1800)
        try:
            conn = db()
            n = conn.execute("SELECT COUNT(*) FROM feedback WHERE verdict IN ('confirm','reject','wrong_category') AND COALESCE(source,'') NOT IN ('test','gold_suite')").fetchone()[0]
            last = conn.execute("SELECT COALESCE(MAX(n_train),0) FROM model_registry").fetchone()[0]
            gold = conn.execute("SELECT COUNT(*) FROM feedback WHERE source='gold_suite'").fetchone()[0]
            if n + gold - last >= 10:
                if not gold: training.seed_gold(conn)
                log.info("auto-retrain: %s", training.retrain(conn).get("status"))
        except Exception as ex:  # noqa
            log.warning("auto-retrain failed: %s", ex)


if os.environ.get("REVIEW_AUTO_RETRAIN", "1") == "1":
    threading.Thread(target=_auto_retrain_loop, daemon=True).start()
_idx = {}


def db():
    return open_db(CFG)


def indexes():
    if os.environ.get("REVIEW_LITE") == "1": return None, None      # small servers: no embedding model in memory
    if "rules" not in _idx:
        try:
            _idx["rules"], _idx["prec"] = kb_index.Index("rules"), kb_index.Index("precedents")
        except Exception as ex:  # noqa
            log.warning("index unavailable: %s", ex); _idx["rules"] = _idx["prec"] = None
    return _idx["rules"], _idx["prec"]


def _write_report(review_id, report):
    """Write the report; if the existing file is not writable (e.g. created by the Docker container as root), write a
    sibling and point the job at it. Reviews must never fail because of a file owned by another user."""
    path = REVIEWS / f"{review_id}.json"
    data = json.dumps(report, ensure_ascii=False, indent=1)
    try:
        path.write_text(data, encoding="utf-8")
    except PermissionError:
        path = REVIEWS / f"{review_id}.v2.json"; path.write_text(data, encoding="utf-8")
        with LOCK: JOBS[review_id]["report_path"] = str(path)
    return path


def run_review(review_id, clauses, source, use_llm, doc=None):
    """Phase 1 (seconds): rules + retrieval -> report is DONE and visible. Phase 2 (minutes, optional): LLM explanations are
    added to the same report one finding at a time, serialised across reviews; the UI shows llm_status and refreshes."""
    try:
        conn = db()
        findings = rv.analyze(clauses, doc)
        rules_idx, prec_idx = indexes()
        for f in findings:
            f["evidence_objects"] = rv.resolve_evidence(conn, f["evidence"], rules_idx, prec_idx, f["clause_text"], f["analysis_type"], f["label"])
        by = {}
        for f in findings: by.setdefault(f["analysis_type"], []).append(f)
        scopes = {}
        for c in clauses: scopes[c.get("scope", "?")] = scopes.get(c.get("scope", "?"), 0) + 1
        want_llm = use_llm and explain.available() and os.environ.get("REVIEW_USE_LLM", "1") not in ("0", "false", "no")
        todo = [f for f in findings if explain.wants_llm(f)] if want_llm else []
        with LOCK: up = JOBS[review_id].get("upload_path")
        report = {"review_id": review_id, "source": source, "reviewed_at": datetime.datetime.now().isoformat(timespec="seconds"), "upload_path": up,
                  "llm_used": False, "llm_status": ("pending" if todo else ("off" if not use_llm else "unavailable")), "llm_total": len(todo), "llm_done": 0,
                  "n_clauses": len(clauses), "clause_scopes": scopes,
                  "kb_release": {"legal_rules": conn.execute("SELECT COUNT(*) FROM legal_rules").fetchone()[0],
                                 "fas_findings": conn.execute("SELECT COUNT(*) FROM fas_findings").fetchone()[0]},
                  "summary": {k: {"findings": len(v), "errors": sum(x["severity"] == "ERROR" for x in v), "risks": sum(x["severity"] == "RISK" for x in v)} for k, v in by.items()},
                  "conclusion": rv.conclusion(findings, doc), "document_view": rep.document_view(doc, clauses), "findings": findings}
        report["edited_clauses"] = sorted({c["clause_id"] for c in clauses if c.get("edited")})
        report["edits"] = _edits_for(review_id)
        path = _write_report(review_id, report)
        try:
            (REVIEWS / f"{review_id}.doc.json").write_text(json.dumps({"doc": doc, "clauses": clauses}, ensure_ascii=False), encoding="utf-8")
        except PermissionError:
            pass
        try: store.save_review(conn, report, up)
        except Exception as ex: log.warning("store.save_review failed: %s", ex)  # noqa
        with LOCK: JOBS[review_id].update(status="done", report_path=str(path), finished=datetime.datetime.now().isoformat(timespec="seconds"),
                                          summary=report["summary"], llm_status=report["llm_status"], llm_total=len(todo), llm_done=0,
                                          n_edits=len(report["edits"]))
        if not todo: return
        with LLM_JOBS:                                   # one LLM review at a time; others wait here with their rule report already visible
            with LOCK: JOBS[review_id]["llm_status"] = "running"
            report["llm_status"] = "running"
            for i, f in enumerate(todo, 1):
                explain.explain(f, f["evidence_objects"])
                report["llm_done"] = i; report["llm_used"] = True
                _write_report(review_id, report)
                with LOCK: JOBS[review_id].update(llm_done=i)
            report["llm_status"] = "done"; _write_report(review_id, report)
            try: store.save_review(db(), report, up)
            except Exception as ex: log.warning("store.save_review failed: %s", ex)  # noqa
            with LOCK: JOBS[review_id].update(llm_status="done")
    except Exception as ex:  # noqa
        log.exception("review failed")
        with LOCK: JOBS[review_id].update(status="error", error=str(ex)[:300])


def start(clauses, source, use_llm, doc=None):
    rid = "R" + uuid.uuid4().hex[:10]
    with LOCK: JOBS[rid] = {"review_id": rid, "status": "running", "source": source, "use_llm": use_llm, "started": datetime.datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=run_review, args=(rid, clauses, source, use_llm, doc), daemon=True).start()
    return rid


@app.post("/api/reviews")
async def create_review(file: UploadFile = File(...), use_llm: bool = Form(True)):
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
    rid = start(clauses, file.filename, use_llm, doc)
    with LOCK: JOBS[rid]["upload_path"] = str(path if path.suffix.lower() == ".docx" else dest); JOBS[rid]["upload_is_docx"] = path.suffix.lower() == ".docx"
    return {"review_id": rid, "status": "running", "n_clauses": len(clauses)}


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


def _find_upload(source):
    """Latest kept upload whose original name matches the review source (uploads are stored as <hash>_<name>)."""
    safe = re.sub(r"[^\w.\-]", "_", source or "")[:120]
    cands = sorted(UPLOADS.glob(f"*_{safe}"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _upgrade_legacy(rid, j):
    """Reports written before the document view existed: regenerate from the kept upload (rule phase only, seconds)."""
    src = _find_upload(j["source"])
    if not src: return False
    try:
        path = rv.prepare_file(src)
        doc = ingest.parse(path); clauses = doc["clauses"]
        for c in clauses: c["document_name"] = j["source"]
        with LOCK: JOBS[rid].update(upload_path=str(path), upload_is_docx=path.suffix.lower() == ".docx", use_llm=False)
        run_review(rid, clauses, j["source"], False, doc)      # synchronous; overwrites the report in place
        with LOCK: JOBS[rid]["legacy"] = False
        return True
    except Exception as ex:  # noqa
        log.warning("legacy upgrade failed for %s: %s", rid, ex); return False


@app.get("/api/reviews/{rid}")
def get_review(rid: str):
    j = JOBS.get(rid)
    if not j: raise HTTPException(404, "unknown review")
    if j["status"] != "done": return j
    if j.get("legacy"): _upgrade_legacy(rid, JOBS[rid]); j = JOBS[rid]
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    report.setdefault("edits", _edits_for(rid)); report.setdefault("edited_clauses", sorted({e["clause_id"] for e in report["edits"]}))
    report["feedback"] = store.feedback_for(db(), rid)
    return {**j, "report": report}


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


@app.get("/api/reviews/{rid}/annotated.docx")
def annotated_docx(rid: str):
    """The uploaded DOCX itself with highlights and Word comments on every flagged fragment."""
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "report not ready")
    src = j.get("upload_path")
    if not src or not j.get("upload_is_docx") or not Path(src).exists():
        raise HTTPException(409, "размеченная копия доступна только для загруженных DOCX (для PDF используйте отчёт)")
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    out = REVIEWS / f"{rid}.annotated.docx"
    annotate.annotate_docx(Path(src), report["findings"], out)
    base = re.sub(r"[^\w.-]", "_", Path(report["source"]).stem)[:60]
    return FileResponse(str(out), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=f"{base}_с_пометками.docx")


def _edits_for(rid):
    try:
        rows = db().execute("SELECT edit_id, clause_id, anchor, labels, categories, original_text, proposed_text, new_text, method, resolved, "
                            "findings_before, findings_after, user_id, created_at FROM edits WHERE review_id=? ORDER BY created_at", (rid,)).fetchall()
        return [dict(r) for r in rows]
    except Exception:  # noqa
        return []


def _load_doc(rid):
    """Working copy of the document for editing. Reviews made before editing existed have none: rebuild it from the kept
    upload (parse again and replay any stored edits), so every review is editable."""
    p = REVIEWS / f"{rid}.doc.json"
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8")); return d.get("doc"), d.get("clauses")
    j = JOBS.get(rid) or {}
    src = Path(j["upload_path"]) if j.get("upload_path") and Path(j["upload_path"]).exists() else _find_upload(j.get("source"))
    if not src: return None, None
    try:
        path = rv.prepare_file(Path(src)); doc = ingest.parse(path)
    except Exception as ex:  # noqa
        log.warning("cannot rebuild working copy for %s: %s", rid, ex); return None, None
    for c in doc["clauses"]: c["document_name"] = j.get("source")
    for e in _edits_for(rid): ed.apply_edit(doc, e["clause_id"], e["new_text"])
    with LOCK:
        JOBS[rid]["upload_path"] = str(path); JOBS[rid]["upload_is_docx"] = path.suffix.lower() == ".docx"
    try:
        p.write_text(json.dumps({"doc": doc, "clauses": doc["clauses"]}, ensure_ascii=False), encoding="utf-8")
    except PermissionError:
        pass
    return doc, doc["clauses"]


class EditIn(BaseModel):
    clause_id: str
    new_text: str
    method: str = "manual"            # manual | suggestion | llm | llm_edited
    finding_ids: list = []
    proposed_text: str | None = None
    user_id: str | None = None


@app.post("/api/reviews/{rid}/edits")
def apply_edit(rid: str, body: EditIn, request: Request):
    """Apply one edit to the working document, re-run the full check synchronously, store the edit as training data."""
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "review not ready")
    doc, clauses = _load_doc(rid)
    if clauses is None: raise HTTPException(409, "исходный файл этой проверки не найден на сервере: загрузите документ заново")
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    before = [f for f in report["findings"] if f.get("clause_id") == body.clause_id]
    if doc is not None:
        old, ok = ed.apply_edit(doc, body.clause_id, body.new_text); clauses = doc["clauses"]
    else:
        old, ok = None, False
        for c in clauses:
            if c["clause_id"] == body.clause_id: old, ok = c["clause_text"], True; c["clause_text"] = body.new_text; c["edited"] = True
    if not ok: raise HTTPException(404, "clause not found")
    with LOCK: JOBS[rid]["status"] = "running"
    run_review(rid, clauses, j["source"], False, doc)        # synchronous re-check (rules + retrieval; LLM explanations are not re-run)
    j = JOBS[rid]
    new_report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    after = [f for f in new_report["findings"] if f.get("clause_id") == body.clause_id]
    edit_id = "E" + uuid.uuid4().hex[:10]
    conn = db()
    conn.execute("INSERT INTO edits(edit_id, review_id, source, clause_id, anchor, finding_ids, labels, categories, original_text, proposed_text, new_text, method, "
                 "resolved, findings_before, findings_after, user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (edit_id, rid, j["source"], body.clause_id, (before[0].get("anchors") or [None])[0] if before else None, json.dumps(body.finding_ids),
                  json.dumps([f["label"] for f in before], ensure_ascii=False), json.dumps([f.get("case_category") for f in before], ensure_ascii=False),
                  old, body.proposed_text, body.new_text, body.method, int(len(after) == 0), len(before), len(after), _uid(request) or body.user_id))
    conn.commit()
    new_report["edits"] = _edits_for(rid); new_report["edited_clauses"] = sorted(set(new_report.get("edited_clauses", [])) | {body.clause_id})
    _write_report(rid, new_report)
    with LOCK: JOBS[rid]["n_edits"] = len(new_report["edits"])
    return {"edit_id": edit_id, "findings_before": len(before), "findings_after": len(after), "resolved": len(after) == 0,
            "total_findings": len(new_report["findings"]), "report": new_report, **{k: v for k, v in JOBS[rid].items()}}


class SuggestIn(BaseModel):
    clause_id: str
    finding_id: str | None = None


@app.post("/api/reviews/{rid}/suggest")
def suggest(rid: str, body: SuggestIn):
    """Automatic correction for one finding: verified rule rewrite / ОКПД2 suggestion / local LLM fallback."""
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "review not ready")
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    fs = [f for f in report["findings"] if f.get("clause_id") == body.clause_id]
    if body.finding_id: fs = [f for f in fs if f["finding_id"] == body.finding_id] or fs
    if not fs: raise HTTPException(404, "no finding for this clause")
    doc, clauses = _load_doc(rid)
    text = next((c["clause_text"] for c in (clauses or []) if c["clause_id"] == body.clause_id), fs[0]["clause_text"])
    p = autofix.propose(fs[0], text, doc, fs[0].get("evidence_objects"), allow_llm=explain.available())
    if not p:
        return {"proposed_text": None, "original": text, "message": "Автоматически это не исправить: нужны сведения, которых нет в документе. " + (fs[0].get("proposed_text") or "")}
    return {"proposed_text": p["new_text"], "original": text, "method": p["method"], "would_resolve": p["would_resolve"], "note": p["note"], "options": p.get("options")}


@app.get("/api/reviews/{rid}/edited.docx")
def edited_docx(rid: str):
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "report not ready")
    src = j.get("upload_path")
    if not src or not j.get("upload_is_docx") or not Path(src).exists(): raise HTTPException(409, "исправленная копия доступна только для загруженных DOCX")
    latest = {}
    for e in _edits_for(rid): latest[e["clause_id"]] = e["new_text"]
    if not latest: raise HTTPException(409, "правок ещё нет")
    out = REVIEWS / f"{rid}.edited.docx"; ed.export_edited_docx(Path(src), latest, out)
    base = re.sub(r"[^\w.-]", "_", Path(j["source"]).stem)[:60]
    return FileResponse(str(out), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=f"{base}_исправлено.docx")


@app.get("/api/edits")
def list_edits(format: str = "json"):
    """All edits ever made: the training set for a correction model."""
    rows = [dict(r) for r in db().execute("SELECT * FROM edits ORDER BY created_at").fetchall()]
    if format == "jsonl":
        p = REVIEWS / "edits_export.jsonl"; p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return FileResponse(str(p), media_type="application/x-ndjson", filename="edits.jsonl")
    return {"count": len(rows), "resolved": sum(r["resolved"] or 0 for r in rows), "by_method": {m: sum(1 for r in rows if r["method"] == m) for m in {r["method"] for r in rows}}, "edits": rows}


class FeedbackIn(BaseModel):
    verdict: str                      # confirm | reject | wrong_category | missed | comment
    finding_id: str | None = None
    clause_id: str | None = None
    correct_category: str | None = None
    comment: str | None = None
    user_id: str | None = None


@app.post("/api/reviews/{rid}/feedback")
def post_feedback(rid: str, body: FeedbackIn, request: Request):
    """Reviewer's verdict on a finding (confirm / reject / wrong category), a comment, or an issue the system missed."""
    if body.verdict not in ("confirm", "reject", "wrong_category", "missed", "comment"): raise HTTPException(400, "bad verdict")
    j = JOBS.get(rid)
    if not j or j["status"] != "done": raise HTTPException(404, "review not ready")
    report = json.loads(Path(j["report_path"]).read_text(encoding="utf-8"))
    f = next((x for x in report["findings"] if x["finding_id"] == body.finding_id), None) if body.finding_id else None
    if body.finding_id and not f: raise HTTPException(404, "finding not found (the document was re-checked; reload)")
    clause_text = None
    if body.clause_id and not f:
        clause_text = next((c["text"] for c in report.get("document_view", []) if c.get("type") == "p" and c.get("clause_id") == body.clause_id), None)
        if clause_text is None:
            clause_text = next((" | ".join(r["cells"]) for b in report.get("document_view", []) if b.get("type") == "table" for r in b["rows"] if r["clause_id"] == body.clause_id), None)
    fid = store.add_feedback(db(), rid, body.verdict, finding=f, clause_id=body.clause_id, clause_text=clause_text,
                             correct_category=body.correct_category, comment=body.comment, user_id=_uid(request) or body.user_id)
    return {"feedback_id": fid, "feedback": store.feedback_for(db(), rid)}


@app.get("/api/reviews/{rid}/feedback")
def get_feedback(rid: str):
    return store.feedback_for(db(), rid)


@app.get("/api/training/stats")
def training_stats():
    s = store.stats(db())
    s["filter_active"] = (training.FILTER_DIR / "active.joblib").exists()
    return s


@app.post("/api/training/export")
def training_export():
    out, manifest = training.export(db())
    return {"path": str(out.relative_to(ROOT)), "manifest": manifest, "files": sorted(p.name for p in out.iterdir())}


@app.get("/api/training/export/{stamp}/{name}")
def training_file(stamp: str, name: str):
    p = training.OUT / stamp / name
    if not re.fullmatch(r"[\w.]+", stamp + name) or not p.exists(): raise HTTPException(404)
    return FileResponse(str(p), filename=name)


TRAIN_STATE = {"status": "idle"}


@app.post("/api/training/retrain")
def training_retrain(seed_gold: bool = False):
    """Runs in the background: optional gold seed → export → train finding filter → gold-suite gate → promote/reject."""
    if TRAIN_STATE["status"] == "running": return TRAIN_STATE
    def job():
        TRAIN_STATE.update(status="running", started=datetime.datetime.now().isoformat(timespec="seconds"), result=None)
        try:
            conn = db()
            if seed_gold: TRAIN_STATE["seed"] = training.seed_gold(conn)
            TRAIN_STATE["result"] = training.retrain(conn); TRAIN_STATE["status"] = "done"
        except Exception as ex:  # noqa
            log.exception("retrain failed"); TRAIN_STATE.update(status="error", error=str(ex)[:300])
    threading.Thread(target=job, daemon=True).start()
    return {"status": "started"}


@app.get("/api/training/retrain")
def training_retrain_status():
    return TRAIN_STATE


SAMPLES = ROOT / "data" / "samples"
CASE = ROOT / "data" / "case"
SAMPLE_FILES = [("lift_source.docx", "Замена грузового лифта (работы)", CASE), ("metrology_source.docx", "Метрологическое оборудование (поставка)", CASE),
                ("it_hardware_tz.docx", "Вычислительная техника (поставка)", SAMPLES), ("synthetic_cleaning.pdf", "Клининговые услуги (PDF)", SAMPLES)]


@app.get("/api/samples")
def samples():
    return [{"name": n, "title": tl} for n, tl, d in SAMPLE_FILES if (d / n).exists()]


@app.post("/api/samples/{name}")
def review_sample(name: str):
    src = next((d / n for n, tl, d in SAMPLE_FILES if n == name and (d / n).exists()), None)
    if not src: raise HTTPException(404, "sample not found")
    dest = UPLOADS / (uuid.uuid4().hex[:8] + "_" + name); shutil.copy(src, dest)
    path = rv.prepare_file(dest); doc = ingest.parse(path)
    for c in doc["clauses"]: c["document_name"] = name
    rid = start(doc["clauses"], name, explain.available(), doc)
    with LOCK: JOBS[rid]["upload_path"] = str(path); JOBS[rid]["upload_is_docx"] = path.suffix.lower() == ".docx"
    return {"review_id": rid, "status": "running"}


@app.get("/api/kb")
def kb():
    conn = db()
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("procurements", "documents", "clauses", "legal_rules", "law_texts", "fas_cases", "fas_documents", "fas_findings")}
    r, p = indexes()
    return {"counts": counts, "retrieval_index": bool(r), "lite": os.environ.get("REVIEW_LITE") == "1", "llm_available": explain.available(), "lexicon_terms": len(checks.LEX["vague_terms"]),
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
