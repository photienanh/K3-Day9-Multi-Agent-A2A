"""First-match EC_POLICY_V1 engine and deterministic submission builder."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .data_repository import DataRepository, decimal_money
from .schemas import CaseOutput


class PolicyResolutionError(RuntimeError):
    """Raised when no EC_POLICY_V1 branch applies to a source snapshot."""


CONFIDENCE_BY_ISSUE = {
    "canceled_order_paid": 0.92,
    "unavailable_order_paid": 0.92,
    "late_delivery_seller": 0.92,
    "late_delivery_logistics": 0.92,
    "valid_split_payment": 0.92,
    "unsupported_late_claim": 0.92,
}


def evaluate_policy(facts: dict[str, Any]) -> dict[str, Any]:
    """Apply the six rules in their required priority order."""

    status = facts["order"]["order_status"]
    totals = facts["totals"]
    payment_total = Decimal(totals["payment_total_brl"])
    freight_total = Decimal(totals["freight_total_brl"])
    delivered_late = facts["delivery"]["delivered_after_estimate"]
    late_seller_ids = facts["late_seller_ids"]

    if status == "canceled" and payment_total > 0:
        issue = "canceled_order_paid"
        cause = "ORDER_CANCELED_AFTER_PAYMENT"
        parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund = payment_total
        action = "issue_full_refund"
    elif status == "unavailable" and payment_total > 0:
        issue = "unavailable_order_paid"
        cause = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
        parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund = payment_total
        action = "issue_full_refund"
    elif delivered_late and late_seller_ids:
        issue = "late_delivery_seller"
        cause = "SELLER_HANDOFF_AFTER_LIMIT"
        parties = [
            {"party_type": "seller", "party_id": seller_id}
            for seller_id in late_seller_ids[:3]
        ]
        refund = freight_total
        action = "refund_freight"
    elif delivered_late:
        issue = "late_delivery_logistics"
        cause = "CARRIER_DELIVERED_AFTER_ESTIMATE"
        parties = [
            {
                "party_type": "logistics_provider",
                "party_id": "LOGISTICS_PROVIDER",
            }
        ]
        refund = freight_total
        action = "refund_freight"
    elif totals["payment_row_count"] >= 2 and totals["totals_reconciled"]:
        issue = "valid_split_payment"
        cause = "MULTIPLE_PAYMENTS_RECONCILED"
        parties = []
        refund = Decimal("0")
        action = "explain_valid_split_payment"
    elif not delivered_late and totals["totals_reconciled"]:
        issue = "unsupported_late_claim"
        cause = "DELIVERY_WITHIN_ESTIMATE"
        parties = []
        refund = Decimal("0")
        action = "reject_late_refund"
    else:
        raise PolicyResolutionError(
            f"No {facts['case']['policy_version']} rule matched "
            f"case {facts['case']['case_id']}"
        )

    refund = decimal_money(refund)
    return {
        "primary_issue": issue,
        "case_status": "action_required" if refund > 0 else "no_action",
        "confidence": CONFIDENCE_BY_ISSUE[issue],
        "root_cause_code": cause,
        "responsible_parties": parties,
        "recommended_refund_brl": f"{refund:.2f}",
        "action": action,
    }


def policy_model_projection(decision: dict[str, Any]) -> dict[str, Any]:
    """Project a deterministic decision onto the Policy Agent's schema."""

    parties = decision["responsible_parties"]
    return {
        "primary_issue": decision["primary_issue"],
        "root_cause_code": decision["root_cause_code"],
        "responsible_party_type": parties[0]["party_type"] if parties else "none",
        "responsible_party_ids": [party["party_id"] for party in parties],
        "recommended_refund_brl": float(decision["recommended_refund_brl"]),
        "action": decision["action"],
    }


def build_case_output(facts: dict[str, Any], decision: dict[str, Any]) -> CaseOutput:
    """Build all IDs and financial values only from verified source rows."""

    case_id = facts["case"]["case_id"]
    order_id = facts["order"]["order_id"]
    item_ids = [f"{order_id}:{item['order_item_id']}" for item in facts["items"]]
    payment_ids = [
        f"{order_id}:{payment['payment_sequential']}"
        for payment in facts["payments"]
    ]
    seller_ids = facts["seller_ids"]

    source_evidence = [f"order:{order_id}"]
    source_evidence.extend(f"item:{item_id}" for item_id in item_ids)
    source_evidence.extend(f"payment:{payment_id}" for payment_id in payment_ids)
    source_evidence.extend(f"seller:{seller_id}" for seller_id in seller_ids)
    policy_evidence = f"policy:{decision['root_cause_code']}"
    evidence_ids = source_evidence[:9] + [policy_evidence]

    totals = facts["totals"]
    return CaseOutput.model_validate(
        {
            "case_id": case_id,
            "assessment": {
                "primary_issue": decision["primary_issue"],
                "case_status": decision["case_status"],
                "confidence": decision["confidence"],
            },
            "affected_entities": {
                "order_ids": [order_id],
                "item_ids": item_ids[:5],
                "seller_ids": seller_ids[:5],
                "payment_ids": payment_ids[:5],
            },
            "root_cause_analysis": {
                "ranked_causes": [
                    {"cause_code": decision["root_cause_code"], "rank": 1}
                ],
                "responsible_parties": decision["responsible_parties"][:3],
            },
            "evidence_ids": evidence_ids,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": float(totals["item_total_brl"]),
                "freight_total_brl": float(totals["freight_total_brl"]),
                "payment_total_brl": float(totals["payment_total_brl"]),
                "recommended_refund_brl": float(
                    decision["recommended_refund_brl"]
                ),
            },
            "resolution_actions": [decision["action"]],
        }
    )


def verify_case_output(
    output: CaseOutput | dict[str, Any], facts: dict[str, Any]
) -> dict[str, Any]:
    """Independently reconstruct the oracle and return auditable check results."""

    candidate = (
        output if isinstance(output, CaseOutput) else CaseOutput.model_validate(output)
    )
    expected_decision = evaluate_policy(facts)
    expected = build_case_output(facts, expected_decision)
    candidate_json = candidate.model_dump(mode="json")
    expected_json = expected.model_dump(mode="json")
    if candidate_json != expected_json:
        raise ValueError(
            f"{facts['case']['case_id']}: candidate differs from policy oracle"
        )

    valid_evidence = DataRepository.valid_evidence_ids(facts)
    valid_evidence.add(f"policy:{expected_decision['root_cause_code']}")
    unexpected_evidence = sorted(set(candidate.evidence_ids) - valid_evidence)
    if unexpected_evidence:
        raise ValueError(
            f"{facts['case']['case_id']}: invalid evidence {unexpected_evidence}"
        )
    if len(candidate.evidence_ids) != len(set(candidate.evidence_ids)):
        raise ValueError(f"{facts['case']['case_id']}: duplicate evidence IDs")

    financial = candidate.financial_resolution
    refund = Decimal(str(financial.recommended_refund_brl))
    expected_refund = Decimal(expected_decision["recommended_refund_brl"])
    if decimal_money(refund) != decimal_money(expected_refund):
        raise ValueError(f"{facts['case']['case_id']}: refund mismatch")

    return {
        "schema_valid": True,
        "policy_priority_valid": True,
        "entities_from_source": True,
        "evidence_from_source": True,
        "money_rounded_2dp": True,
        "refund_valid": True,
        "cardinality_limits_valid": True,
        "primary_issue": expected_decision["primary_issue"],
        "root_cause_code": expected_decision["root_cause_code"],
        "recommended_refund_brl": float(expected_refund),
    }
