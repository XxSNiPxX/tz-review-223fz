#!/usr/bin/env python3
"""CLI entry point.

  python collect.py eis          # FTP crawl + parse 223-ФЗ XML into procurements/documents
  python collect.py eis-html     # fallback: HTML search of zakupki.gov.ru (RU IP)
  python collect.py eis-linked   # fetch the notices referenced by FAS decisions (RU IP)
  python collect.py attachments  # download ТЗ/документация files referenced by notices
  python collect.py convert      # detect real formats, unpack archives, convert doc/xls/rtf (run before extract)
  python collect.py extract      # PDF/DOCX/XLSX -> document_sections + clauses
  python collect.py fas          # br.fas.gov.ru decisions -> fas_cases
  python collect.py fas-relabel  # recompute outcome/articles after regex changes
  python collect.py findings     # per-argument findings from decisions -> fas_findings
  python collect.py amend-dates  # signing/effective dates for amending laws
  python collect.py audit        # data-quality report -> docs/audit_<date>.md
  python collect.py export-annotation  # JSONL samples for manual annotation
  python collect.py legal        # 223-ФЗ / 44-ФЗ text -> legal_rules
  python collect.py all
  python collect.py stats
"""
import argparse, logging, sys
from procdata.common import load_config, open_db, log
from procdata import eis_ftp, eis_parse, eis_attachments, extract_text, fas_br, legal, eis_html, findings, audit, convert, baseline


def cmd_eis(db, cfg, args):
    archives = eis_ftp.crawl(cfg, cfg["_data_dir"])
    log.info("%d archives on disk", len(archives))
    n = 0
    for zp, member, xml in eis_ftp.iter_xml(archives):
        eis_parse.ingest_xml(db, cfg, zp, member, xml, cfg["_data_dir"] / "xml")
        n += 1
        if n % 200 == 0:
            db.commit()
    db.commit()
    log.info("parsed %d xml files", n)


def cmd_stats(db, cfg, args):
    for t in ["procurements", "documents", "clauses", "fas_cases", "fas_documents", "legal_rules", "law_texts"]:
        print(f"{t:18s} {db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    print("documents by status:")
    for r in db.execute("SELECT document_type, extraction_status, COUNT(*) c FROM documents GROUP BY 1,2"):
        print(f"  {r[0]:22s} {r[1]:12s} {r[2]}")
    print("fas document outcomes:")
    for r in db.execute("SELECT COALESCE(law_type,'?'), COALESCE(outcome,'?'), COUNT(*) FROM fas_documents GROUP BY 1,2"):
        print(f"  {r[0]:8s} {r[1]:18s} {r[2]}")
    print("law texts:")
    for r in db.execute("SELECT law, source, n_articles FROM law_texts ORDER BY 1,2"):
        print(f"  {r[0]:8s} {r[1]:28s} {r[2]} articles")
    print("legal_rules by source:")
    for r in db.execute("SELECT law, source, COUNT(*) FROM legal_rules GROUP BY 1,2"):
        print(f"  {r[0]:8s} {r[1]:12s} {r[2]}")


COMMANDS = {
    "eis": cmd_eis,
    "attachments": lambda db, cfg, a: eis_attachments.download_pending(db, cfg, cfg["_data_dir"], a.limit),
    "extract": lambda db, cfg, a: extract_text.extract_all(db, cfg, a.limit),
    "convert": lambda db, cfg, a: convert.run(db, a.limit),
    "baseline": lambda db, cfg, a: baseline.run(db),
    "eis-html": lambda db, cfg, a: eis_html.collect(db, cfg, cfg["_data_dir"]),
    "eis-linked": lambda db, cfg, a: eis_html.collect_linked(db, cfg, cfg["_data_dir"], a.limit),
    "fas": lambda db, cfg, a: fas_br.collect(db, cfg, cfg["_data_dir"]),
    "fas-relabel": lambda db, cfg, a: fas_br.relabel(db),
    "findings": lambda db, cfg, a: findings.extract_all(db, a.limit),
    "amend-dates": lambda db, cfg, a: audit.fill_amendment_dates(db),
    "audit": lambda db, cfg, a: audit.run(db),
    "export-annotation": lambda db, cfg, a: audit.export_annotation(db, cfg["_data_dir"] / "processed" / "annotation"),
    "legal": lambda db, cfg, a: legal.collect(db, cfg, cfg["_data_dir"]),
    "stats": cmd_stats,
}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=list(COMMANDS) + ["all"])
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--limit", type=int, default=None, help="max items for attachments/extract")
    p.add_argument("--sources", default=None, help="legal only: comma list overriding config (e.g. ruslawod)")
    p.add_argument("-v", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_config(args.config)
    if args.sources:
        cfg["legal"]["sources"] = args.sources.split(",")
    db = open_db(cfg)
    steps = ["legal", "eis", "attachments", "extract", "fas", "stats"] if args.command == "all" else [args.command]
    for st in steps:
        log.info("=== %s ===", st)
        COMMANDS[st](db, cfg, args)
    db.commit()
