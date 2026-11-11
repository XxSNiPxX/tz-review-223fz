"""Download attachment files referenced by notices (ТЗ, документация, проект договора).

URLs look like https://zakupki.gov.ru/223/purchase/public/download/download.html?id=<n>
zakupki.gov.ru blocks non-Russian IPs and bare python user agents; run from a RU host or via a RU proxy.
"""
import re, time
from pathlib import Path
from .common import log, http_session, sha256_file, polite_get


def download_pending(db, cfg, out_dir: Path, limit=None):
    e = cfg["eis"]
    s = http_session(e["http_user_agent"])
    rows = db.execute("SELECT document_id, procurement_id, source_url, original_filename FROM documents "
                      "WHERE document_type='attachment' AND extraction_status='pending'"
                      + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
    log.info("%d attachments pending", len(rows))
    for r in rows:
        dest_dir = out_dir / "attachments" / r["procurement_id"].replace(":", "_")
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^\w.\-() А-Яа-яЁё]", "_", r["original_filename"] or "file.bin")
        stem, ext = Path(fname).stem, Path(fname).suffix[:8]
        while len((stem + ext).encode("utf-8")) > 150:   # ext4 limit is 255 bytes; Cyrillic is 2 bytes/char
            stem = stem[:-5]
        uid = r["document_id"].rsplit(":", 1)[-1][:12]
        dest = dest_dir / f"{uid}_{stem}{ext}"
        resp = polite_get(s, r["source_url"], delay=e["attachment_delay_sec"], stream=True)
        if resp is None:
            db.execute("UPDATE documents SET extraction_status='failed', error='http' WHERE document_id=?",
                       (r["document_id"],)); db.commit(); continue
        ctype = resp.headers.get("Content-Type", "")
        if "text/html" in ctype and not fname.lower().endswith((".htm", ".html")):
            # Got an HTML page instead of the file: probably a block page / captcha.
            db.execute("UPDATE documents SET extraction_status='failed', error='html_instead_of_file' WHERE document_id=?",
                       (r["document_id"],)); db.commit(); continue
        try:
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(1 << 16):
                    f.write(chunk)
        except Exception as ex:  # read timeout / connection reset mid-body: keep going, retry on the next run
            dest.unlink(missing_ok=True)
            log.warning("body read failed for %s: %s", r["source_url"], type(ex).__name__)
            db.execute("UPDATE documents SET extraction_status='pending', error='read_failed_retry' WHERE document_id=?",
                       (r["document_id"],)); db.commit(); continue
        db.execute("UPDATE documents SET storage_path=?, file_hash=?, extraction_status='downloaded', error=NULL "
                   "WHERE document_id=?", (str(dest), sha256_file(dest), r["document_id"]))
        db.commit()
