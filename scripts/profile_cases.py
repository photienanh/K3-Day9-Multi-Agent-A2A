# -*- coding: utf-8 -*-
"""Profile 50 input cases against Olist CSVs to map every logic branch and edge case."""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

orders = pd.read_csv(ROOT / "data/olist_orders_dataset.csv", dtype=str)
items = pd.read_csv(ROOT / "data/olist_order_items_dataset.csv", dtype=str)
payments = pd.read_csv(ROOT / "data/olist_order_payments_dataset.csv", dtype=str)

items["price"] = items["price"].astype(float)
items["freight_value"] = items["freight_value"].astype(float)
payments["payment_value"] = payments["payment_value"].astype(float)

orders_idx = orders.set_index("order_id")

rows = []
for f in sorted((ROOT / "input").glob("EC_*.json")):
    case = json.loads(f.read_text(encoding="utf-8"))
    oid = case["customer_request"]["claimed_order_id"]
    r = {"case_id": case["case_id"], "order_id": oid}

    if oid not in orders_idx.index:
        r["issue"] = "ORDER_NOT_FOUND"
        rows.append(r)
        continue

    o = orders_idx.loc[oid]
    it = items[items["order_id"] == oid]
    pay = payments[payments["order_id"] == oid]

    r["status"] = o["order_status"]
    r["n_items"] = len(it)
    r["n_sellers"] = it["seller_id"].nunique()
    r["n_payments"] = len(pay)
    item_total = round(it["price"].sum(), 2)
    freight_total = round(it["freight_value"].sum(), 2)
    pay_total = round(pay["payment_value"].sum(), 2)
    r["item_total"] = item_total
    r["freight_total"] = freight_total
    r["pay_total"] = pay_total
    r["pay_match"] = abs(pay_total - (item_total + freight_total)) <= 0.10

    est = o["order_estimated_delivery_date"]
    delivered = o["order_delivered_customer_date"]
    carrier = o["order_delivered_carrier_date"]
    r["has_delivered"] = pd.notna(delivered)
    r["has_carrier"] = pd.notna(carrier)
    r["late"] = pd.notna(delivered) and pd.notna(est) and delivered > est

    seller_late = []
    if pd.notna(carrier):
        for _, row in it.iterrows():
            if carrier > row["shipping_limit_date"]:
                seller_late.append(row["seller_id"])
    r["sellers_late"] = sorted(set(seller_late))
    r["mixed_seller_late"] = 0 < len(set(seller_late)) < r["n_sellers"]

    # classify per priority
    if o["order_status"] == "canceled" and pay_total > 0:
        r["issue"] = "canceled_order_paid"
    elif o["order_status"] == "unavailable" and pay_total > 0:
        r["issue"] = "unavailable_order_paid"
    elif r["late"] and seller_late:
        r["issue"] = "late_delivery_seller"
    elif r["late"]:
        r["issue"] = "late_delivery_logistics"
    elif len(pay) >= 2 and r["pay_match"]:
        r["issue"] = "valid_split_payment"
    elif not r["late"] and r["pay_match"]:
        r["issue"] = "unsupported_late_claim"
    else:
        r["issue"] = "UNCLASSIFIED"
    rows.append(r)

df = pd.DataFrame(rows)
pd.set_option("display.width", 250)
print("=== ISSUE DISTRIBUTION ===")
print(df["issue"].value_counts().to_string())
print("\n=== ANOMALIES / EDGE CASES ===")
print("order not found:", df[df["issue"] == "ORDER_NOT_FOUND"]["case_id"].tolist())
print("unclassified:", df[df["issue"] == "UNCLASSIFIED"]["case_id"].tolist())
print("no items:", df[df.get("n_items", 0) == 0]["case_id"].tolist())
print("no payments:", df[df.get("n_payments", 0) == 0]["case_id"].tolist())
print("multi-seller:", df[df["n_sellers"] > 1]["case_id"].tolist())
print("mixed seller lateness:", df[df["mixed_seller_late"] == True]["case_id"].tolist())
print("late but pay mismatch:", df[(df["late"] == True) & (df["pay_match"] == False)]["case_id"].tolist())
print("not late & pay mismatch:", df[(df["late"] == False) & (df["pay_match"] == False)]["case_id"].tolist())
print("delivered status but missing delivered date:",
      df[(df["status"] == "delivered") & (df["has_delivered"] == False)]["case_id"].tolist())
print("status not delivered/canceled/unavailable:",
      df[~df["status"].isin(["delivered", "canceled", "unavailable"])][["case_id", "status"]].to_dict("records"))
print("canceled/unavailable with items:",
      df[df["status"].isin(["canceled", "unavailable"]) & (df["n_items"] > 0)]["case_id"].tolist())
print("late_delivery + >=2 payments (priority overlap):",
      df[df["issue"].str.startswith("late_delivery") & (df["n_payments"] >= 2)]["case_id"].tolist())
print("\n=== FULL TABLE ===")
print(df.to_string(index=False))
