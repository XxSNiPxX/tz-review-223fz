#!/usr/bin/env bash
# Package the minimal knowledge base the review server needs (no attachments, no raw HTML):
#   data/procurement.sqlite, data/index/, kb/  ->  kb_release_<date>.tar.gz
# A clean checkout runs with:  tar xzf kb_release_*.tar.gz && docker compose up -d
set -e
cd "$(dirname "$0")"
OUT="kb_release_$(date +%Y%m%d).tar.gz"
test -f data/procurement.sqlite || { echo "no data/procurement.sqlite; run the collectors first"; exit 1; }
test -d data/index || { echo "no data/index; run: python review.py --build-index"; exit 1; }
sqlite3 data/procurement.sqlite "VACUUM;" 2>/dev/null || true
tar czf "$OUT" data/procurement.sqlite data/index kb docs/eval_latest.md
ls -la "$OUT"
sha256sum "$OUT" > "$OUT.sha256"
