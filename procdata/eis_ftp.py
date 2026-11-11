"""Crawl the public ЕИС FTP (ftp.zakupki.gov.ru, login free/free) for 223-ФЗ XML archives.

Layout (223-ФЗ):  /out/published/<Region>/<docType>/daily/<docType>_<Region>_<YYYYMMDD>_..._daily_NNN.xml.zip
Each zip holds one or more XML files; each XML is one notice / protocol / explanation.
44-ФЗ lives under /fcs_regions/<Region>/... and uses different XML schemas; not handled here.
"""
import re, zipfile
from datetime import datetime
from ftplib import FTP, error_perm
from pathlib import Path
from .common import log

DATE_RE = re.compile(r"_(\d{8})_\d{6}_(\d{8})_\d{6}_")


def _archive_dates(name):
    m = DATE_RE.search(name)
    if not m:
        return None, None
    return (datetime.strptime(m.group(1), "%Y%m%d").date(), datetime.strptime(m.group(2), "%Y%m%d").date())


def crawl(cfg, out_dir: Path):
    e = cfg["eis"]
    d_from, d_to = datetime.fromisoformat(e["date_from"]).date(), datetime.fromisoformat(e["date_to"]).date()
    ftp = FTP(e["ftp_host"], timeout=120)
    ftp.login(e["ftp_user"], e["ftp_password"])
    ftp.set_pasv(True)
    downloaded = []
    for region in e["regions"]:
        region_dir = f"{e['root']}/{region}"
        try:
            subdirs = [Path(p).name for p in ftp.nlst(region_dir)]
        except error_perm as ex:
            log.error("cannot list %s: %s", region_dir, ex); continue
        wanted = [s for s in subdirs if any(s.startswith(p) for p in e["doc_type_prefixes"])]
        log.info("%s: %d matching doc-type dirs: %s", region, len(wanted), wanted)
        for doc_type in wanted:
            daily = f"{region_dir}/{doc_type}/daily"
            try:
                names = [Path(p).name for p in ftp.nlst(daily)]
            except error_perm:
                log.warning("no daily dir at %s", daily); continue
            picked = []
            for n in names:
                if not n.endswith(".zip"):
                    continue
                a, b = _archive_dates(n)
                if a and b and b >= d_from and a <= d_to:
                    picked.append(n)
            picked = sorted(picked)[: e["max_archives_per_dir"]]
            dest_dir = out_dir / "ftp" / region / doc_type
            dest_dir.mkdir(parents=True, exist_ok=True)
            for n in picked:
                dest = dest_dir / n
                if dest.exists() and dest.stat().st_size > 0:
                    downloaded.append(dest); continue
                log.info("fetch %s/%s", daily, n)
                try:
                    with open(dest, "wb") as f:
                        ftp.retrbinary(f"RETR {daily}/{n}", f.write)
                    downloaded.append(dest)
                except Exception as ex:
                    log.error("download failed %s: %s", n, ex)
                    dest.unlink(missing_ok=True)
    ftp.quit()
    return downloaded


def iter_xml(archives):
    """Yield (archive_path, member_name, xml_bytes) for every XML inside the zips."""
    for zp in archives:
        try:
            with zipfile.ZipFile(zp) as z:
                for m in z.namelist():
                    if m.lower().endswith(".xml"):
                        yield zp, m, z.read(m)
        except zipfile.BadZipFile:
            log.error("bad zip %s", zp)
