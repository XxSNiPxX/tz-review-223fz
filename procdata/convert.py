"""Normalise downloaded attachments before text extraction.

1. Detect the real type with `file --mime-type` (filename suffixes on ЕИС are unreliable) and fix documents.file_format.
2. HTML served instead of a file = block page -> back to 'pending' for a retry.
3. Legacy Office (doc/xls/rtf/odt) -> docx/xlsx via headless LibreOffice, stored next to the original in converted/.
4. Archives (zip/rar/7z) -> unpacked with 7z into <uid>_unpacked/; every inner file becomes its own documents row
   (document_id <parent>/<n>), the archive row is marked 'unpacked'.
Originals are never deleted. Requires: file, soffice, 7z.
"""
import re, shutil, subprocess
from pathlib import Path
from .common import log, upsert, sha256_file

MIME_EXT = {
    "application/pdf": "PDF", "application/msword": "DOC", "text/rtf": "RTF", "application/rtf": "RTF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-excel": "XLS", "application/vnd.oasis.opendocument.text": "ODT",
    "application/vnd.oasis.opendocument.spreadsheet": "ODS", "application/zip": "ZIP",
    "application/x-rar": "RAR", "application/vnd.rar": "RAR", "application/x-7z-compressed": "7Z",
    "text/html": "HTML", "text/plain": "TXT", "application/json": "JSON", "image/jpeg": "JPG", "image/png": "PNG",
    "image/tiff": "TIFF", "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
}
CONVERT = {"DOC": "docx", "RTF": "docx", "ODT": "docx", "XLS": "xlsx", "ODS": "xlsx"}
ARCHIVE = {"ZIP", "RAR", "7Z"}
SKIP_INNER = re.compile(r"(\.(sig|p7s|exe|dll|db|ini|lnk)$|^__MACOSX/|/\._|Thumbs\.db$)", re.I)


def mime(path):
    try:
        return subprocess.run(["file", "--mime-type", "-b", str(path)], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as ex:  # noqa
        log.warning("file(1) failed on %s: %s", path, ex); return ""


def fix_formats(db):
    rows = db.execute("SELECT document_id, storage_path FROM documents WHERE document_type='attachment' "
                      "AND storage_path IS NOT NULL AND extraction_status IN ('downloaded','failed','extracted')").fetchall()
    n_fix = n_html = 0
    for r in rows:
        p = Path(r["storage_path"])
        if not p.exists(): continue
        fmt = MIME_EXT.get(mime(p))
        if fmt is None: continue
        if fmt == "HTML" and p.suffix.lower() not in (".htm", ".html"):
            db.execute("UPDATE documents SET file_format='HTML', extraction_status='pending', error='html_instead_of_file' WHERE document_id=?", (r["document_id"],))
            n_html += 1; continue
        cur = db.execute("SELECT file_format, extraction_status FROM documents WHERE document_id=?", (r["document_id"],)).fetchone()
        if cur["file_format"] != fmt:
            n_fix += 1
            # a previously 'unsupported_format' failure may now be readable
            st = "downloaded" if cur["extraction_status"] == "failed" and fmt in ("PDF", "DOCX", "XLSX") else cur["extraction_status"]
            db.execute("UPDATE documents SET file_format=?, extraction_status=?, error=NULL WHERE document_id=?", (fmt, st, r["document_id"]))
    db.commit()
    log.info("formats: %d corrected from content, %d block pages reset to pending", n_fix, n_html)


def _soffice(src: Path, target: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["soffice", "--headless", "--norestore", "--convert-to", target, "--outdir", str(out_dir), str(src)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=180, env={"HOME": str(out_dir), "PATH": "/usr/bin:/bin"})
    out = out_dir / (src.stem + "." + target)
    return out if out.exists() and out.stat().st_size > 0 else None


def convert_legacy(db, limit=None):
    rows = db.execute("SELECT document_id, storage_path, file_format FROM documents WHERE document_type='attachment' "
                      "AND file_format IN ('DOC','RTF','ODT','XLS','ODS') AND extraction_status IN ('downloaded','failed') AND storage_path IS NOT NULL"
                      + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    ok = 0
    for r in rows:
        src = Path(r["storage_path"])
        if not src.exists(): continue
        try:
            out = _soffice(src, CONVERT[r["file_format"]], src.parent / "converted")
        except Exception as ex:  # noqa
            out = None; log.warning("soffice failed on %s: %s", src.name, ex)
        if out is None:
            db.execute("UPDATE documents SET extraction_status='failed', error='conversion_failed' WHERE document_id=?", (r["document_id"],)); continue
        db.execute("UPDATE documents SET storage_path=?, file_format=?, extraction_status='downloaded', error=NULL, "
                   "description=COALESCE(description,'') || ' [converted from ' || ? || ': ' || ? || ']' WHERE document_id=?",
                   (str(out), CONVERT[r["file_format"]].upper(), r["file_format"], src.name, r["document_id"]))
        ok += 1
        db.commit()
    log.info("legacy conversion: %d/%d converted", ok, len(rows))


def unpack_archives(db, limit=None):
    rows = db.execute("SELECT document_id, procurement_id, storage_path, original_filename FROM documents WHERE document_type='attachment' "
                      "AND file_format IN ('ZIP','RAR','7Z') AND extraction_status IN ('downloaded','failed') AND storage_path IS NOT NULL"
                      + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    n_arch = n_inner = 0
    for r in rows:
        src = Path(r["storage_path"])
        if not src.exists(): continue
        dest = src.parent / (src.stem[:40] + "_unpacked")
        if dest.exists(): shutil.rmtree(dest)
        res = subprocess.run(["7z", "x", "-y", "-p", f"-o{dest}", str(src)], capture_output=True, text=True, timeout=300)
        # 7z returns 1/2 for warnings (e.g. odd headers) while still extracting; judge by the result
        if not dest.exists() or not any(dest.rglob("*")):
            db.execute("UPDATE documents SET extraction_status='failed', error=? WHERE document_id=?",
                       ("unpack_failed: " + (res.stderr or res.stdout)[-150:], r["document_id"])); continue
        inner = [p for p in sorted(dest.rglob("*")) if p.is_file() and not SKIP_INNER.search(str(p.relative_to(dest)))]
        for i, p in enumerate(inner, 1):
            fmt = MIME_EXT.get(mime(p)) or (p.suffix.lstrip(".").upper() or None)
            upsert(db, "documents", {
                "document_id": f"{r['document_id']}/{i}", "procurement_id": r["procurement_id"], "document_type": "attachment",
                "original_filename": str(p.relative_to(dest)), "description": f"from archive {r['original_filename']}",
                "source_url": None, "storage_path": str(p), "file_hash": sha256_file(p), "file_format": fmt,
                "extraction_status": "downloaded" if fmt in ("PDF", "DOCX", "XLSX", "DOC", "RTF", "XLS", "ODT", "ZIP", "RAR", "7Z") else "failed",
                "error": None if fmt in ("PDF", "DOCX", "XLSX", "DOC", "RTF", "XLS", "ODT", "ZIP", "RAR", "7Z") else "unsupported_format"}, "document_id")
            n_inner += 1
        db.execute("UPDATE documents SET extraction_status='unpacked', error=NULL WHERE document_id=?", (r["document_id"],))
        n_arch += 1
        db.commit()
    log.info("archives: %d unpacked, %d inner files registered", n_arch, n_inner)


def run(db, limit=None):
    fix_formats(db)
    unpack_archives(db, limit)       # may register nested legacy files / archives
    unpack_archives(db, limit)       # one level of nesting
    convert_legacy(db, limit)
