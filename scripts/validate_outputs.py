# -*- coding: utf-8 -*-
"""Independent end-to-end validation of output/ against the CSVs and the spec."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

ISSUES = {"canceled_order_paid", "unavailable_order_paid", "late_delivery_seller",
          "late_delivery_logistics", "valid_split_payment", "unsupported_late_claim"}
CODES = {"SELLER_HANDOFF_AFTER_LIMIT", "CARRIER_DELIVERED_AFTER_ESTIMATE",
         "ORDER_CANCELED_AFTER_PAYMENT", "ORDER_UNAVAILABLE_AFTER_PAYMENT",
         "MULTIPLE_PAYMENTS_RECONCILED", "DELIVERY_WITHIN_ESTIMATE"}
ISSUE_TO_CODE = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOFF_AFTER_LIMIT",
    "late_delivery_logistics": "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "valid_split_payment": "MULTIPLE_PAYMENTS_RECONCILED",
    "unsupported_late_claim": "DELIVERY_WITHIN_ESTIMATE",
}
ISSUE_TO_ACTION = {
    "canceled_order_paid": "issue_full_refund",
    "unavailable_order_paid": "issue_full_refund",
    "late_delivery_seller": "refund_freight",
    "late_delivery_logistics": "refund_freight",
    "valid_split_payment": "explain_valid_split_payment",
    "unsupported_late_claim": "reject_late_refund",
}

orders = pd.read_csv(ROOT / "data/olist_orders_dataset.csv", dtype=str).set_index("order_id")
items_df = pd.read_csv(ROOT / "data/olist_order_items_dataset.csv", dtype=str)
items_df["price"] = items_df["price"].astype(float)
items_df["freight_value"] = items_df["freight_value"].astype(float)
pays_df = pd.read_csv(ROOT / "data/olist_order_payments_dataset.csv", dtype=str)
pays_df["payment_value"] = pays_df["payment_value"].astype(float)
sellers_all = set(pd.read_csv(ROOT / "data/olist_sellers_dataset.csv", dtype=str)["seller_id"])


def expected_for(order_id):
    o = orders.loc[order_id]
    it = items_df[items_df["order_id"] == order_id]
    pay = pays_df[pays_df["order_id"] == order_id]
    item_total = round(it["price"].sum(), 2) if len(it) else 0.0
    freight_total = round(it["freight_value"].sum(), 2) if len(it) else 0.0
    pay_total = round(pay["payment_value"].sum(), 2) if len(pay) else 0.0
    delivered = o["order_delivered_customer_date"]
    est = o["order_estimated_delivery_date"]
    carrier = o["order_delivered_carrier_date"]
    late = pd.notna(delivered) and pd.notna(est) and delivered > est
    sellers_late = sorted({r["seller_id"] for _, r in it.iterrows()
                           if pd.notna(carrier) and carrier > r["shipping_limit_date"]})
    match = abs(pay_total - (item_total + freight_total)) <= 0.10
    if o["order_status"] == "canceled" and pay_total > 0:
        issue, refund, party = "canceled_order_paid", pay_total, ("platform", "OLIST_PLATFORM")
    elif o["order_status"] == "unavailable" and pay_total > 0:
        issue, refund, party = "unavailable_order_paid", pay_total, ("platform", "OLIST_PLATFORM")
    elif late and sellers_late:
        issue, refund, party = "late_delivery_seller", freight_total, ("seller", sellers_late[0])
    elif late:
        issue, refund, party = "late_delivery_logistics", freight_total, ("logistics_provider", "LOGISTICS_PROVIDER")
    elif len(pay) >= 2 and match:
        issue, refund, party = "valid_split_payment", 0.0, None
    else:
        issue, refund, party = "unsupported_late_claim", 0.0, None
    return {
        "issue": issue, "refund": refund, "party": party,
        "item_total": item_total, "freight_total": freight_total, "pay_total": pay_total,
        "item_ids": {f"{order_id}:{r['order_item_id']}" for _, r in it.iterrows()},
        "seller_ids": set(it["seller_id"]) if len(it) else set(),
        "payment_ids": {f"{order_id}:{r['payment_sequential']}" for _, r in pay.iterrows()},
    }


def two_decimals(x):
    return abs(x - round(x, 2)) < 1e-9


failures = []


def check(case_id, cond, msg):
    if not cond:
        failures.append(f"{case_id}: {msg}")


input_files = sorted((ROOT / "input").glob("EC_*.json"))
output_files = sorted((ROOT / "output").glob("EC_*.json"))
assert len(input_files) == 50
check("GLOBAL", len(output_files) == 50, f"expected 50 outputs, found {len(output_files)}")

for inp in input_files:
    case = json.loads(inp.read_text(encoding="utf-8"))
    cid = case["case_id"]
    oid = case["customer_request"]["claimed_order_id"]
    out_path = ROOT / "output" / inp.name
    if not out_path.exists():
        check(cid, False, "missing output file")
        continue
    out = json.loads(out_path.read_text(encoding="utf-8"))
    exp = expected_for(oid)

    check(cid, out["case_id"] == cid, "case_id mismatch")
    a = out["assessment"]
    check(cid, a["primary_issue"] in ISSUES, f"bad primary_issue {a['primary_issue']}")
    check(cid, a["case_status"] in ("action_required", "no_action"), "bad case_status")
    check(cid, isinstance(a["confidence"], (int, float)) and 0 <= a["confidence"] <= 1,
          "confidence out of range")
    check(cid, a["primary_issue"] == exp["issue"],
          f"issue {a['primary_issue']} != expected {exp['issue']}")
    expected_status = "action_required" if exp["refund"] > 0 else "no_action"
    check(cid, a["case_status"] == expected_status, "case_status inconsistent with refund")

    ent = out["affected_entities"]
    check(cid, ent["order_ids"] == [oid], "order_ids wrong")
    check(cid, set(ent["item_ids"]) == exp["item_ids"] or
          (len(exp["item_ids"]) > 5 and len(ent["item_ids"]) == 5), "item_ids wrong")
    check(cid, set(ent["seller_ids"]) == exp["seller_ids"] or
          (len(exp["seller_ids"]) > 5 and len(ent["seller_ids"]) == 5), "seller_ids wrong")
    check(cid, set(ent["payment_ids"]) == exp["payment_ids"] or
          (len(exp["payment_ids"]) > 5 and len(ent["payment_ids"]) == 5), "payment_ids wrong")

    rca = out["root_cause_analysis"]
    check(cid, rca["ranked_causes"][0]["cause_code"] == ISSUE_TO_CODE[exp["issue"]],
          "rank-1 cause wrong")
    if exp["party"] is None:
        check(cid, rca["responsible_parties"] == [], "expected no responsible party")
    else:
        check(cid, len(rca["responsible_parties"]) == 1 and
              rca["responsible_parties"][0]["party_type"] == exp["party"][0] and
              rca["responsible_parties"][0]["party_id"] == exp["party"][1],
              f"party wrong, expected {exp['party']}")

    ev = out["evidence_ids"]
    check(cid, 1 <= len(ev) <= 10, "evidence count out of bounds")
    check(cid, len(ev) == len(set(ev)), "duplicate evidence ids")
    has_policy = False
    for e in ev:
        p = e.split(":")
        if p[0] == "order":
            check(cid, len(p) == 2 and p[1] in orders.index, f"bad evidence {e}")
        elif p[0] == "item":
            check(cid, len(p) == 3 and f"{p[1]}:{p[2]}" in exp["item_ids"], f"bad evidence {e}")
        elif p[0] == "payment":
            check(cid, len(p) == 3 and f"{p[1]}:{p[2]}" in exp["payment_ids"], f"bad evidence {e}")
        elif p[0] == "seller":
            check(cid, len(p) == 2 and p[1] in sellers_all, f"bad evidence {e}")
        elif p[0] == "policy":
            has_policy = True
            check(cid, len(p) == 2 and p[1] == ISSUE_TO_CODE[exp["issue"]], f"bad evidence {e}")
        else:
            check(cid, False, f"unknown evidence kind {e}")
    check(cid, has_policy, "missing policy evidence")

    fin = out["financial_resolution"]
    check(cid, fin["currency"] == "BRL", "currency")
    check(cid, abs(fin["item_total_brl"] - exp["item_total"]) < 0.005, "item_total wrong")
    check(cid, abs(fin["freight_total_brl"] - exp["freight_total"]) < 0.005, "freight_total wrong")
    check(cid, abs(fin["payment_total_brl"] - exp["pay_total"]) < 0.005, "payment_total wrong")
    check(cid, abs(fin["recommended_refund_brl"] - exp["refund"]) < 0.005, "refund wrong")
    for k in ("item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"):
        check(cid, two_decimals(fin[k]), f"{k} not rounded to 2 decimals")
    check(cid, out["resolution_actions"] == [ISSUE_TO_ACTION[exp["issue"]]],
          f"actions wrong: {out['resolution_actions']}")

print(f"Checked {len(input_files)} cases.")
if failures:
    print(f"\nFAILURES ({len(failures)}):")
    for f in failures:
        print(" -", f)
    raise SystemExit(1)
print("ALL CHECKS PASSED")
