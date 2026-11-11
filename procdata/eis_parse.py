"""Parse 223-ФЗ ЕИС XML (purchaseNotice*, purchaseProtocol*, explanation) into the DB.

The XML uses several namespaces (http://zakupki.gov.ru/223fz/purchase/1, .../types/1 ...), and the exact
element set differs per notice type. We therefore match on local names only and keep the raw XML on disk.
"""
import json
from pathlib import Path
from lxml import etree
from .common import log, upsert, sha256_file


def _ln(el):
    return etree.QName(el).localname


def _first(root, *localnames):
    """Depth-first search for the first element whose local-name path ends with localnames."""
    for el in root.iter():
        if _ln(el) == localnames[-1]:
            node, ok = el, True
            for want in reversed(localnames[:-1]):
                node = node.getparent()
                if node is None or _ln(node) != want:
                    ok = False; break
            if ok:
                return el
    return None


def _text(root, *path):
    el = _first(root, *path)
    return (el.text or "").strip() if el is not None and el.text else None


def _float(v):
    try:
        return float(v.replace(",", ".")) if v else None
    except ValueError:
        return None


def parse_notice(xml_bytes):
    root = etree.fromstring(xml_bytes)
    body = _first(root, "body")
    if body is None:
        body = root
    reg = _text(body, "registrationNumber")
    if not reg:
        return None
    proc = {
        "procurement_id": f"EIS223:{reg}",
        "eis_id": reg,
        "law_type": "223-FZ",
        "customer_id": _text(body, "customer", "mainInfo", "inn") or _text(body, "customer", "inn"),
        "customer_name": _text(body, "customer", "mainInfo", "fullName") or _text(body, "customer", "fullName"),
        "procurement_method": _text(body, "purchaseMethodName") or _text(body, "purchaseCodeName"),
        "name": _text(body, "name") or _text(body, "purchaseName"),
        "okpd2_code": _text(body, "okpd2", "code"),
        "initial_price": _float(_text(body, "initialSum")) or _float(_text(body, "lotData", "initialSum")),
        "currency": _text(body, "currency", "code"),
        "publication_date": _text(body, "publicationDateTime"),
        "submission_deadline": _text(body, "submissionCloseDateTime"),
        "procurement_status": _text(body, "status"),
        "source_url": _text(body, "urlEIS") or _text(body, "urlOOS")
                       or (f"https://zakupki.gov.ru/223/purchase/public/purchase/info/common-info.html?regNumber={reg}"),
    }
    attachments = []
    for doc in body.iter():
        if _ln(doc) == "document" and doc.getparent() is not None and _ln(doc.getparent()) == "attachments":
            attachments.append({
                "guid": _text(doc, "guid"),
                "fileName": _text(doc, "fileName"),
                "description": _text(doc, "description"),
                "url": _text(doc, "url"),
            })
    return proc, attachments


def ingest_xml(db, cfg, archive: Path, member: str, xml_bytes: bytes, raw_dir: Path):
    doc_kind = archive.parent.name  # purchaseNotice / purchaseProtocol... from the FTP path
    try:
        parsed = parse_notice(xml_bytes)
    except etree.XMLSyntaxError as ex:
        log.error("bad xml %s!%s: %s", archive.name, member, ex); return
    if not parsed:
        return
    proc, attachments = parsed
    raw_path = raw_dir / archive.parent.parent.name / doc_kind / Path(member).name
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(xml_bytes)
    proc["region"] = archive.parent.parent.name
    proc["source_archive"] = str(archive)
    if doc_kind.startswith("purchaseNotice"):
        proc["raw_xml_path"] = str(raw_path)
        upsert(db, "procurements", proc, "procurement_id")
    else:
        # protocol/explanation: make sure the procurement row exists (may arrive before its notice)
        db.execute("INSERT OR IGNORE INTO procurements(procurement_id, eis_id, law_type, region) VALUES (?,?,?,?)",
                   (proc["procurement_id"], proc["eis_id"], "223-FZ", proc["region"]))
    upsert(db, "documents", {
        "document_id": f"{proc['procurement_id']}:{doc_kind}:{Path(member).stem}",
        "procurement_id": proc["procurement_id"],
        "document_type": f"{doc_kind}_xml",
        "original_filename": member,
        "storage_path": str(raw_path),
        "file_hash": sha256_file(raw_path),
        "file_format": "XML",
        "publication_date": proc.get("publication_date"),
        "extraction_status": "downloaded",
    }, "document_id")
    for a in attachments:
        if not a.get("url"):
            continue
        upsert(db, "documents", {
            "document_id": f"{proc['procurement_id']}:att:{a.get('guid') or a['fileName']}",
            "procurement_id": proc["procurement_id"],
            "document_type": "attachment",
            "original_filename": a.get("fileName"),
            "description": a.get("description"),
            "source_url": a["url"],
            "file_format": (Path(a.get("fileName") or "").suffix.lstrip(".").upper() or None),
            "publication_date": proc.get("publication_date"),
            "extraction_status": "pending",
        }, "document_id")
