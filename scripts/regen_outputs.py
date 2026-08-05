# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipeline import (  # noqa: E402
    DataStore, OrderSellerAgent, PaymentAgent, DeliveryAgent, PolicyAgent, VerifierAgent,
)

ROOT = Path(__file__).resolve().parents[1]
store = DataStore(ROOT)
oa, pa, da = OrderSellerAgent(store), PaymentAgent(store), DeliveryAgent()
pol, ver = PolicyAgent(), VerifierAgent(store)

for f in sorted((ROOT / "input").glob("EC_*.json")):
    case = json.loads(f.read_text(encoding="utf-8"))
    oid = case["customer_request"]["claimed_order_id"]
    of = oa.analyze(oid)
    pf = pa.analyze(oid, of.get("item_total", 0), of.get("freight_total", 0))
    df = da.analyze(of)
    dec = pol.decide(of, pf, df)
    out = pol.draft(case["case_id"], of, pf, dec)
    errs = ver.verify(out)
    if errs:
        raise SystemExit(f"{case['case_id']} verify fail {errs}")
    (ROOT / "output" / f.name).write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sev = [e for e in out["evidence_ids"] if e.startswith("seller:")]
    print(case["case_id"], out["assessment"]["primary_issue"],
          "seller_ev", sev, "seller_ids", out["affected_entities"]["seller_ids"])
print("OK")
