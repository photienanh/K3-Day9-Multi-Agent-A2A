# -*- coding: utf-8 -*-
import json
from pathlib import Path

for f in sorted(Path("output").glob("EC_*.json")):
    o = json.loads(f.read_text(encoding="utf-8"))
    issue = o["assessment"]["primary_issue"]
    ev = o["evidence_ids"]
    sellers = [e for e in ev if e.startswith("seller:")]
    print(
        f"{o['case_id']} {issue:28} conf={o['assessment']['confidence']} "
        f"n_ev={len(ev)} sellers={sellers} "
        f"seller_ids={o['affected_entities']['seller_ids']} "
        f"parties={o['root_cause_analysis']['responsible_parties']}"
    )
