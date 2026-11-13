#!/usr/bin/env python3
"""Measure auto-fix quality on the gold documents: for each finding, apply the proposed fix to a copy of the document,
re-run the full review, and check that (a) the finding on that fragment is gone and (b) no new ERROR/RISK appears there."""
import copy, json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from procdata import ingest, autofix, edits
import review as rv

DOCS = ["data/case/lift_source.docx", "data/case/metrology_source.docx", "kb/gold/synthetic_cleaning.docx", "kb/gold/it_hardware_tz.docx"]


def text_of(doc, cid):
    for c in doc["clauses"]:
        if c["clause_id"] == cid: return c["clause_text"]


def main():
    per = defaultdict(lambda: {"findings": 0, "proposed": 0, "resolved": 0, "new_problems": 0})
    examples = []
    for path in DOCS:
        doc = ingest.parse(Path(path)); base = rv.analyze(doc["clauses"], doc)
        for f in base:
            if not f.get("clause_id") or f["severity"] == "NOTE" and f["label"] not in ("NUMBER_WITHOUT_WORDS",): continue
            s = per[f["label"]]; s["findings"] += 1
            old = text_of(doc, f["clause_id"])
            if old is None: continue
            p = autofix.propose(f, old, doc, allow_llm=False)
            if not p: continue
            s["proposed"] += 1
            d2 = copy.deepcopy(doc); edits.apply_edit(d2, f["clause_id"], p["new_text"])
            after = rv.analyze(d2["clauses"], d2)
            same = [x for x in after if x.get("clause_id") == f["clause_id"] and x["label"] == f["label"]]
            before_ids = {(x["label"]) for x in base if x.get("clause_id") == f["clause_id"]}
            new = [x for x in after if x.get("clause_id") == f["clause_id"] and x["label"] not in before_ids and x["severity"] in ("ERROR", "RISK") and x["disposition"] == "FLAGGED"]
            s["resolved"] += not same; s["new_problems"] += bool(new)
            if len(examples) < 14: examples.append((f["label"], old[:90], p["new_text"][:110], "OK" if not same else "STILL"))
    tot = {k: sum(v[k] for v in per.values()) for k in ("findings", "proposed", "resolved", "new_problems")}
    print(f"{'label':30s} {'found':>5s} {'fix':>5s} {'cleared':>7s} {'new':>4s}")
    for lab, v in sorted(per.items()):
        print(f"{lab:30s} {v['findings']:5d} {v['proposed']:5d} {v['resolved']:7d} {v['new_problems']:4d}")
    print(f"\nTOTAL findings {tot['findings']} | auto-fix proposed {tot['proposed']} | cleared after re-check {tot['resolved']} | introduced new problems {tot['new_problems']}")
    print("\nexamples:")
    for e in examples: print(f"  [{e[3]}] {e[0]}: «{e[1]}» -> «{e[2]}»")


if __name__ == "__main__":
    main()
