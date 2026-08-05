"""Deterministic loading and joining of the Olist source rows."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR, INPUT_DIR, MONEY_TOLERANCE_BRL, POLICY_VERSION


MONEY_QUANTUM = Decimal("0.01")
CASE_FILE_RE = re.compile(r"EC_\d{3}\.json")


class DataContractError(RuntimeError):
    """Raised when an input or CSV row violates the assignment contract."""


def parse_csv_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def decimal_money(value: str | Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def money_text(value: Decimal) -> str:
    return f"{decimal_money(value):.2f}"


def _unique_in_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


class DataRepository:
    """Indexes only the four tables needed by the dispute workflow."""

    def __init__(self, input_dir: Path = INPUT_DIR, data_dir: Path = DATA_DIR) -> None:
        self.input_dir = input_dir
        self.data_dir = data_dir
        self.cases = self._load_cases()
        order_ids = {
            case["customer_request"]["claimed_order_id"] for case in self.cases
        }
        self.orders = self._load_orders(order_ids)
        self.items = self._load_grouped_rows(
            data_dir / "olist_order_items_dataset.csv", order_ids
        )
        self.payments = self._load_grouped_rows(
            data_dir / "olist_order_payments_dataset.csv", order_ids
        )
        self.seller_ids = self._load_seller_ids()
        self._validate_references(order_ids)

    def _load_cases(self) -> list[dict[str, Any]]:
        paths = sorted(
            path
            for path in self.input_dir.glob("EC_*.json")
            if CASE_FILE_RE.fullmatch(path.name)
        )
        if not paths:
            raise DataContractError(f"No EC_*.json cases found in {self.input_dir}")

        cases: list[dict[str, Any]] = []
        seen_case_ids: set[str] = set()
        seen_order_ids: set[str] = set()
        for path in paths:
            with path.open(encoding="utf-8") as handle:
                case = json.load(handle)
            case_id = case.get("case_id")
            expected_case_id = path.stem
            if case_id != expected_case_id:
                raise DataContractError(
                    f"{path.name}: case_id {case_id!r} != {expected_case_id!r}"
                )
            if case_id in seen_case_ids:
                raise DataContractError(f"Duplicate case_id: {case_id}")
            if case.get("policy_version") != POLICY_VERSION:
                raise DataContractError(
                    f"{case_id}: expected policy_version {POLICY_VERSION}"
                )
            request = case.get("customer_request") or {}
            order_id = request.get("claimed_order_id")
            if not isinstance(order_id, str) or not order_id:
                raise DataContractError(f"{case_id}: missing claimed_order_id")
            if order_id in seen_order_ids:
                raise DataContractError(f"Duplicate claimed_order_id: {order_id}")
            try:
                datetime.fromisoformat(case["opened_at"])
            except (KeyError, TypeError, ValueError) as exc:
                raise DataContractError(f"{case_id}: invalid opened_at") from exc
            seen_case_ids.add(case_id)
            seen_order_ids.add(order_id)
            cases.append(case)
        return cases

    def _load_orders(self, selected_ids: set[str]) -> dict[str, dict[str, str]]:
        orders: dict[str, dict[str, str]] = {}
        path = self.data_dir / "olist_orders_dataset.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                order_id = row["order_id"]
                if order_id in selected_ids:
                    if order_id in orders:
                        raise DataContractError(f"Duplicate order row: {order_id}")
                    orders[order_id] = row
        return orders

    def _load_grouped_rows(
        self, path: Path, selected_ids: set[str]
    ) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["order_id"] in selected_ids:
                    grouped[row["order_id"]].append(row)
        return dict(grouped)

    def _load_seller_ids(self) -> set[str]:
        path = self.data_dir / "olist_sellers_dataset.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            return {row["seller_id"] for row in csv.DictReader(handle)}

    def _validate_references(self, selected_ids: set[str]) -> None:
        missing_orders = sorted(selected_ids - self.orders.keys())
        if missing_orders:
            raise DataContractError(f"Orders not found: {missing_orders}")
        for order_id, rows in self.items.items():
            item_ids = [int(row["order_item_id"]) for row in rows]
            if len(item_ids) != len(set(item_ids)):
                raise DataContractError(f"Duplicate item ID in order {order_id}")
            missing_sellers = sorted(
                {row["seller_id"] for row in rows} - self.seller_ids
            )
            if missing_sellers:
                raise DataContractError(
                    f"Unknown sellers in order {order_id}: {missing_sellers}"
                )
        for order_id, rows in self.payments.items():
            payment_ids = [int(row["payment_sequential"]) for row in rows]
            if len(payment_ids) != len(set(payment_ids)):
                raise DataContractError(f"Duplicate payment ID in order {order_id}")

    def facts_for_case(self, case: dict[str, Any]) -> dict[str, Any]:
        """Return a JSON-safe source snapshot plus deterministic comparisons."""

        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        order = self.orders[order_id]
        item_rows = sorted(
            self.items.get(order_id, []), key=lambda row: int(row["order_item_id"])
        )
        payment_rows = sorted(
            self.payments.get(order_id, []),
            key=lambda row: int(row["payment_sequential"]),
        )

        carrier_at = parse_csv_datetime(order["order_delivered_carrier_date"])
        delivered_at = parse_csv_datetime(order["order_delivered_customer_date"])
        estimated_at = parse_csv_datetime(order["order_estimated_delivery_date"])

        items: list[dict[str, Any]] = []
        late_seller_ids: list[str] = []
        for row in item_rows:
            shipping_limit_at = parse_csv_datetime(row["shipping_limit_date"])
            handoff_after_limit = bool(
                carrier_at and shipping_limit_at and carrier_at > shipping_limit_at
            )
            if handoff_after_limit:
                late_seller_ids.append(row["seller_id"])
            items.append(
                {
                    "order_item_id": int(row["order_item_id"]),
                    "product_id": row["product_id"],
                    "seller_id": row["seller_id"],
                    "shipping_limit_date": row["shipping_limit_date"],
                    "price_brl": money_text(Decimal(row["price"])),
                    "freight_brl": money_text(Decimal(row["freight_value"])),
                    "carrier_handoff_after_limit": handoff_after_limit,
                }
            )

        payments = [
            {
                "payment_sequential": int(row["payment_sequential"]),
                "payment_type": row["payment_type"],
                "payment_installments": int(row["payment_installments"]),
                "payment_value_brl": money_text(Decimal(row["payment_value"])),
            }
            for row in payment_rows
        ]

        item_total = sum(
            (Decimal(row["price"]) for row in item_rows), start=Decimal("0")
        )
        freight_total = sum(
            (Decimal(row["freight_value"]) for row in item_rows),
            start=Decimal("0"),
        )
        payment_total = sum(
            (Decimal(row["payment_value"]) for row in payment_rows),
            start=Decimal("0"),
        )
        discrepancy = payment_total - item_total - freight_total
        totals_reconciled = abs(discrepancy) <= Decimal(MONEY_TOLERANCE_BRL)
        delivered_after_estimate = bool(
            delivered_at and estimated_at and delivered_at > estimated_at
        )

        return {
            "case": {
                "case_id": case_id,
                "opened_at": case["opened_at"],
                "request_language": case["customer_request"].get("language"),
                "claimed_order_id": order_id,
                "policy_version": case["policy_version"],
            },
            "order": {
                "order_id": order_id,
                "customer_id": order["customer_id"],
                "order_status": order["order_status"],
                "order_purchase_timestamp": order["order_purchase_timestamp"],
                "order_approved_at": order["order_approved_at"] or None,
                "order_delivered_carrier_date": order[
                    "order_delivered_carrier_date"
                ]
                or None,
                "order_delivered_customer_date": order[
                    "order_delivered_customer_date"
                ]
                or None,
                "order_estimated_delivery_date": order[
                    "order_estimated_delivery_date"
                ]
                or None,
            },
            "items": items,
            "payments": payments,
            "seller_ids": _unique_in_order(item["seller_id"] for item in items),
            "late_seller_ids": _unique_in_order(late_seller_ids),
            "delivery": {
                "delivered_after_estimate": delivered_after_estimate,
                "delivery_timestamp_present": delivered_at is not None,
            },
            "totals": {
                "item_total_brl": money_text(item_total),
                "freight_total_brl": money_text(freight_total),
                "payment_total_brl": money_text(payment_total),
                "discrepancy_brl": money_text(discrepancy),
                "totals_reconciled": totals_reconciled,
                "payment_row_count": len(payments),
            },
        }

    @staticmethod
    def valid_evidence_ids(facts: dict[str, Any]) -> set[str]:
        order_id = facts["order"]["order_id"]
        evidence = {f"order:{order_id}"}
        evidence.update(
            f"item:{order_id}:{item['order_item_id']}" for item in facts["items"]
        )
        evidence.update(
            f"payment:{order_id}:{payment['payment_sequential']}"
            for payment in facts["payments"]
        )
        evidence.update(f"seller:{seller_id}" for seller_id in facts["seller_ids"])
        return evidence
