import hashlib, logging, os, sqlite3, time, uuid
from pathlib import Path
import requests, yaml

log = logging.getLogger("procdata")
ROOT = Path(__file__).resolve().parent.parent


def load_config(path="config.yaml"):
    with open(ROOT / path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_data_dir"] = (ROOT / cfg["data_dir"]).resolve()
    cfg["_data_dir"].mkdir(parents=True, exist_ok=True)
    return cfg


# Columns added after the first release; applied to existing databases on open.
_MIGRATIONS = {
    "fas_cases": {"case_number": "TEXT", "procedure": "TEXT", "stage": "TEXT", "participants": "TEXT"},
    "legal_rules": {"source": "TEXT", "effective_from": "TEXT", "effective_to": "TEXT", "edition_status": "TEXT"},
    "law_texts": {"signing_date": "TEXT", "publication_date": "TEXT", "effective_date": "TEXT", "effective_date_source": "TEXT"},
    "fas_documents": {"review_status": "TEXT", "outcome_reviewed": "TEXT"},
}


def open_db(cfg):
    db = sqlite3.connect(ROOT / cfg["db_path"])
    db.row_factory = sqlite3.Row
    db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    for table, cols in _MIGRATIONS.items():
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        for c, typ in cols.items():
            if c not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {c} {typ}")
    db.commit()
    return db


def upsert(db, table, row: dict, key: str):
    cols = ", ".join(row)
    qs = ", ".join("?" * len(row))
    updates = ", ".join(f"{c}=excluded.{c}" for c in row if c != key)
    db.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs}) ON CONFLICT({key}) DO UPDATE SET {updates}",
               list(row.values()))


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def http_session(user_agent=None):
    s = requests.Session()
    # zakupki.gov.ru and other .gov.ru hosts use the Russian Trusted Root CA (Минцифры), absent from certifi.
    # certs/ru_bundle.pem = certifi bundle + that root/sub CA; see README. Verification stays on.
    bundle = ROOT / "certs" / "ru_bundle.pem"
    if bundle.exists():
        s.verify = str(bundle)
    s.headers["User-Agent"] = user_agent or "Mozilla/5.0 (X11; Linux x86_64) Chrome/124.0 Safari/537.36"
    s.headers["Accept-Language"] = "ru-RU,ru;q=0.9"
    return s


def polite_get(session, url, delay=1.0, retries=3, timeout=60, **kw):
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                time.sleep(delay)
                return r
            log.warning("GET %s -> %s", url, r.status_code)
            if r.status_code in (404, 410, 403):
                time.sleep(delay)
                return None
            if r.status_code == 429:                      # rate limited: back off hard, then retry
                wait = 60 * (attempt + 1)
                log.warning("429 from %s, sleeping %ds", url.split("?")[0], wait)
                time.sleep(wait)
                continue
        except requests.RequestException as e:
            log.warning("GET %s failed: %s", url, e)
        time.sleep(delay * (attempt + 2))
    return None
