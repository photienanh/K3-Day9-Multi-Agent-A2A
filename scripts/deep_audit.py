# -*- coding: utf-8 -*-
"""Deep audit: compare our outputs against every plausible gold interpretation."""
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
sellers = set(pd.read_csv(ROOT / "data/olist_sellers_dataset.csv", dtype=str)["seller_id"])

ISSUE_CODE = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}


def classify(oid, seller_late_op=">", late_op=">"):
    o = orders.loc[oid]
    it = items[items.order_id == oid]
    pay = pays[pays.order_id == oid]
    item_total = round(it.price.sum(), 2) if len(it) else 0.0
    freight = round(it.freight_value.sum(), 2) if len(it) else 0.0
    pay_total = round(pay.payment_value.sum(), 2) if len(pay) else 0.0
    d, e, c = o.order_delivered_customer_date, o.order_estimated_delivery_date, o.order_delivered_carrier_date
    if late_op == ">":
        late = pd.notna(d) and pd.notna(e) and d > e
    else:
        late = pd.notna(d) and pd.notna(e) and d >= e
    sellers_late = []
    if pd.notna(c):
        for _, r in it.iterrows():
            ok = (c > r.shipping_limit_date) if seller_late_op == ">" else (c >= r.shipping_limit_date)
            if ok:
                sellers_late.append(r.seller_id)
    sellers_late = sorted(set(sellers_late))
    match = abs(pay_total - (item_total + freight)) <= 0.10
    if o.order_status == "canceled" and pay_total > 0:
        return "canceled_order_paid", pay_total, ("platform", "OLIST_PLATFORM"), sellers_late
    if o.order_status == "unavailable" and pay_total > 0:
        return "unavailable_order_paid", pay_total, ("platform", "OLIST_PLATFORM"), sellers_late
    if late and sellers_late:
        return "late_delivery_seller", freight, ("seller", sellers_late[0]), sellers_late
    if late:
        return "late_delivery_logistics", freight, ("logistics_provider", "LOGISTICS_PROVIDER"), sellers_late
    if len(pay) >= 2 and match:
        return "valid_split_payment", 0.0, None, sellers_late
    return "unsupported_late_claim", 0.0, None, sellers_late


def evidence_csv_valid(ev):
    """Simulate naive grader: non-policy must exist in CSV."""
    fps = []
    for e in ev:
        p = e.split(":")
        if p[0] == "order":
            if len(p) != 2 or p[1] not in orders.index:
                fps.append(e)
        elif p[0] == "item":
            if len(p) != 3:
                fps.append(e)
            else:
                it = items[(items.order_id == p[1]) & (items.order_item_id == p[2])]
                if len(it) == 0:
                    fps.append(e)
        elif p[0] == "payment":
            if len(p) != 3:
                fps.append(e)
            else:
                pay = pays[(pays.order_id == p[1]) & (pays.payment_sequential == p[2])]
                if len(pay) == 0:
                    fps.append(e)
        elif p[0] == "seller":
            if len(p) != 2 or p[1] not in sellers:
                fps.append(e)
        elif p[0] == "policy":
            if len(p) != 2 or p[1] not in ISSUE_CODE.values():
                fps.append(e)
        else:
            fps.append(e)
    return fps


print("=== Rule-variant diffs vs current outputs ===")
variants = [
    (">", ">"),
    (">=", ">"),
    (">", ">="),
    (">=", ">="),
]
for sop, lop in variants:
    diffs = []
    for f in sorted((ROOT / "input").glob("EC_*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        oid = case["customer_request"]["claimed_order_id"]
        out = json.loads((ROOT / "output" / f.name).read_text(encoding="utf-8"))
        issue, *_ = classify(oid, sop, lop)
        if issue != out["assessment"]["primary_issue"]:
            diffs.append((case["case_id"], out["assessment"]["primary_issue"], issue))
    print(f"seller_late{sop} late{lop}: {len(diffs)} diffs", diffs[:5])

print("\n=== Evidence CSV-validity FPs ===")
fp_cases = 0
for f in sorted((ROOT / "output").glob("EC_*.json")):
    out = json.loads(f.read_text(encoding="utf-8"))
    fps = evidence_csv_valid(out["evidence_ids"])
    if fps:
        fp_cases += 1
        print(out["case_id"], fps)
print("cases with FP:", fp_cases)

print("\n=== Logistics cases detail ===")
for f in sorted((ROOT / "output").glob("EC_*.json")):
    out = json.loads(f.read_text(encoding="utf-8"))
    if out["assessment"]["primary_issue"] != "late_delivery_logistics":
        continue
    oid = out["affected_entities"]["order_ids"][0]
    o = orders.loc[oid]
    it = items[items.order_id == oid]
    print(
        out["case_id"],
        "carrier", o.order_delivered_carrier_date,
        "est", o.order_estimated_delivery_date,
        "delivered", o.order_delivered_customer_date,
        "limits", list(it.shipping_limit_date),
        "party", out["root_cause_analysis"]["responsible_parties"],
        "sellers_ent", out["affected_entities"]["seller_ids"],
        "ev_sellers", [e for e in out["evidence_ids"] if e.startswith("seller:")],
    )

print("\n=== Party type inventory ===")
from collections import Counter
c = Counter()
for f in sorted((ROOT / "output").glob("EC_*.json")):
    out = json.loads(f.read_text(encoding="utf-8"))
    parties = out["root_cause_analysis"]["responsible_parties"]
    if not parties:
        c[("NONE", out["assessment"]["primary_issue"])] += 1
    else:
        for p in parties:
            c[(p["party_type"], p["party_id"][:20], out["assessment"]["primary_issue"])] += 1
for k, v in c.most_common():
    print(v, k)

print("\n=== Confidence / money sample anomalies ===")
for f in sorted((ROOT / "output").glob("EC_*.json")):
    out = json.loads(f.read_text(encoding="utf-8"))
    fin = out["financial_resolution"]
    # flag money that JSON would print without 2 decimals visually
    for k in ("item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"):
        s = json.dumps(fin[k])
        if "." in s and len(s.split(".")[-1]) == 1:
            print(out["case_id"], k, s, "issue", out["assessment"]["primary_issue"])
            break
