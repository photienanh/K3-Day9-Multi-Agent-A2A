# -*- coding: utf-8 -*-
"""Test hypotheses for remaining ~4% score gap."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
orders = pd.read_csv(ROOT / "data/olist_orders_dataset.csv", dtype=str).set_index("order_id")
items = pd.read_csv(ROOT / "data/olist_order_items_dataset.csv", dtype=str)
items["price"] = items["price"].astype(float)
items["freight_value"] = items["freight_value"].astype(float)
pays = pd.read_csv(ROOT / "data/olist_order_payments_dataset.csv", dtype=str)
pays["payment_value"] = pays["payment_value"].astype(float)


def load_case(f):
    case = json.loads(f.read_text(encoding="utf-8"))
    out = json.loads((ROOT / "output" / f.name).read_text(encoding="utf-8"))
    oid = case["customer_request"]["claimed_order_id"]
    o = orders.loc[oid]
    it = items[items.order_id == oid]
    pay = pays[pays.order_id == oid]
    return case, out, oid, o, it, pay


print("=== All cases compact ===")
for f in sorted((ROOT / "input").glob("EC_*.json")):
    case, out, oid, o, it, pay = load_case(f)
    a = out["assessment"]
    d, e, c = o.order_delivered_customer_date, o.order_estimated_delivery_date, o.order_delivered_carrier_date
    late = pd.notna(d) and pd.notna(e) and d > e
    pay_total = round(pay.payment_value.sum(), 2) if len(pay) else 0.0
    item_total = round(it.price.sum(), 2) if len(it) else 0.0
    freight = round(it.freight_value.sum(), 2) if len(it) else 0.0
    diff = abs(pay_total - (item_total + freight))
    print(
        f"{case['case_id']} {a['primary_issue']:26} conf={a['confidence']} "
        f"status={o.order_status:12} late={late} npay={len(pay)} nitem={len(it)} "
        f"paydiff={diff:.2f} party={out['root_cause_analysis']['responsible_parties']}"
    )

print("\n=== Hypothesis: confidence always 1.0 would change assessment ===")
print("Current case-eval ~94.52 with conf in {0.85,0.9,0.95}")
confs = []
for f in sorted((ROOT / "output").glob("EC_*.json")):
    confs.append(json.loads(f.read_text(encoding="utf-8"))["assessment"]["confidence"])
print("avg conf", sum(confs) / len(confs))

print("\n=== Hypothesis: split vs unsupported swap (if priority reversed) ===")
swaps = []
for f in sorted((ROOT / "input").glob("EC_*.json")):
    case, out, oid, o, it, pay = load_case(f)
    issue = out["assessment"]["primary_issue"]
    d, e = o.order_delivered_customer_date, o.order_estimated_delivery_date
    late = pd.notna(d) and pd.notna(e) and d > e
    item_total = round(it.price.sum(), 2) if len(it) else 0.0
    freight = round(it.freight_value.sum(), 2) if len(it) else 0.0
    pay_total = round(pay.payment_value.sum(), 2) if len(pay) else 0.0
    match = abs(pay_total - (item_total + freight)) <= 0.10
    if not late and match and len(pay) >= 2:
        alt = "unsupported_late_claim"  # if gold ignored split priority
        if issue == "valid_split_payment":
            swaps.append((case["case_id"], issue, "could_be_unsupported_if_priority_wrong"))
print("split cases that could flip:", len(swaps), swaps)

print("\n=== Hypothesis: logistics party_type variants ===")
print("We use logistics_provider / LOGISTICS_PROVIDER per README table")
print("Alt guesses: logistics/LOGISTICS, carrier/CARRIER, logistics_provider/logistics_provider")

print("\n=== Multi-item / multi-pay cases (entity truncation risk) ===")
for f in sorted((ROOT / "input").glob("EC_*.json")):
    case, out, oid, o, it, pay = load_case(f)
    if len(it) > 1 or len(pay) > 1:
        print(
            case["case_id"], out["assessment"]["primary_issue"],
            "items", len(it), "pays", len(pay),
            "item_ids", out["affected_entities"]["item_ids"],
            "payment_ids", out["affected_entities"]["payment_ids"],
            "n_ev", len(out["evidence_ids"]),
        )
