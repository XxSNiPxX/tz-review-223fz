#!/usr/bin/env bash
# Usage: ./run_collect.sh [step ...]   (default: legal fas stats)
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate
python3 -c "import requests, bs4, lxml, yaml" 2>/dev/null || pip install -q -r requirements.txt
python3 - <<'EOF'
import sqlite3, os
if os.path.exists('data/procurement.sqlite'):
    d = sqlite3.connect('data/procurement.sqlite')
    # drop rows produced by the broken first-version legal run
    d.execute("DELETE FROM legal_rules WHERE source IS NULL")
    d.execute("DELETE FROM documents WHERE document_type='law' AND document_id NOT LIKE 'LAW:%:%'")
    d.commit()
EOF
steps="${*:-legal fas stats}"
for s in $steps; do
  echo "=================== $s ==================="
  python3 collect.py "$s" 2>&1 | tee -a data/collect.log | tail -60
done
