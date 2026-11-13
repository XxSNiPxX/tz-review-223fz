#!/usr/bin/env python3
"""Score the review engine against the reviewer corrections shipped with the case (kb/gold/case_gold.json).

Recall: for each *_source document, an expected item counts as found when some finding of the same case category
mentions one of its anchors (in clause_text, matched or anchors). False positives: findings on *_final documents
with severity ERROR/RISK and disposition FLAGGED (NOTE and INSUFFICIENT_EVIDENCE are allowed: "marked for manual check").
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from procdata import ingest, checks, checks_doc

GOLD = json.loads(Path("kb/gold/case_gold.json").read_text(encoding="utf-8"))
CASE_DIR = Path("data/case")


def review(path):
    doc = ingest.parse(path)
    import review as rv
    return doc, rv.analyze(doc["clauses"], doc)


def norm(s): return re.sub(r"\s+", " ", (s or "")).lower()


def main():
    total_must = found_must = total_opt = found_opt = fps = flagged_must = 0
    for name, g in GOLD["documents"].items():
        path = CASE_DIR / name if (CASE_DIR / name).exists() else Path("kb/gold") / name
        doc, fs = review(path)
        print(f"\n=== {name}: {len(fs)} findings, kind={doc['fields']['contract_kind']}")
        if g["expected"]:
            for e in g["expected"]:
                hit = None
                for f in fs:
                    if f.get("case_category") != e["category"]: continue
                    hay = norm(f.get("clause_text")) + " " + norm(" ".join(map(str, f.get("matched") or []))) + " " + norm(f.get("explanation"))
                    if any(norm(a) in hay for a in e["anchors"]): hit = f; break
                tag = "must" if e["must"] else "opt "
                if e["must"]: total_must += 1; found_must += bool(hit); flagged_must += bool(hit and (hit["disposition"] == "FLAGGED" or hit.get("filter_p_reject") is None and hit["disposition"] != "FLAGGED"))
                else: total_opt += 1; found_opt += bool(hit)
                print(f"  [{'OK ' if hit else 'MISS'}] {tag} {e['id']} {e['category']:22s} {e['what'][:80]}" + (f"  <- {hit['label']} ({hit['disposition']})" if hit else ""))
        else:
            bad = [f for f in fs if f["severity"] in ("ERROR", "RISK") and f["disposition"] == "FLAGGED"]
            fps += len(bad)
            for f in fs:
                flag = "FP " if f in bad else "ok "
                print(f"  [{flag}] {f.get('case_category','?'):22s} {f['label']:28s} {f['severity']:5s} {f['disposition']:21s} {f['explanation'][:70]}")
    print(f"\nRECALL must: {found_must}/{total_must}   optional: {found_opt}/{total_opt}   FALSE POSITIVES on corrected docs: {fps}")
    print(f"MUST NOT DOWNGRADED BY FILTER: {flagged_must}/{total_must}")


if __name__ == "__main__":
    main()
