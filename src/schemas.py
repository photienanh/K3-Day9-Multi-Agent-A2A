"""Strict schemas for model handoffs and submission artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PrimaryIssue = Literal[
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
]
CauseCode = Literal[
    "SELLER_HANDOFF_AFTER_LIMIT",
    "CARRIER_DELIVERED_AFTER_ESTIMATE",
    "ORDER_CANCELED_AFTER_PAYMENT",
    "ORDER_UNAVAILABLE_AFTER_PAYMENT",
    "MULTIPLE_PAYMENTS_RECONCILED",
    "DELIVERY_WITHIN_ESTIMATE",
]
ResolutionAction = Literal[
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
]
PartyType = Literal["seller", "platform", "logistics_provider"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assessment(StrictModel):
    primary_issue: PrimaryIssue
    case_status: Literal["action_required", "no_action"]
    confidence: float = Field(ge=0.0, le=1.0)


class AffectedEntities(StrictModel):
    order_ids: list[str] = Field(max_length=5)
    item_ids: list[str] = Field(max_length=5)
    seller_ids: list[str] = Field(max_length=5)
    payment_ids: list[str] = Field(max_length=5)


class RankedCause(StrictModel):
    cause_code: CauseCode
    rank: int = Field(ge=1, le=3)


class ResponsibleParty(StrictModel):
    party_type: PartyType
    party_id: str


class RootCauseAnalysis(StrictModel):
    ranked_causes: list[RankedCause] = Field(max_length=3)
    responsible_parties: list[ResponsibleParty] = Field(max_length=3)


class FinancialResolution(StrictModel):
    currency: Literal["BRL"]
    item_total_brl: float
    freight_total_brl: float
    payment_total_brl: float
    recommended_refund_brl: float


class CaseOutput(StrictModel):
    case_id: str
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: list[str] = Field(max_length=10)
    financial_resolution: FinancialResolution
    resolution_actions: list[ResolutionAction] = Field(max_length=5)


# The following schemas are intentionally compact. They are native Structured
# Output contracts for independent model agents, not the final submission schema.
class OrderSellerReview(StrictModel):
    order_status: str
    seller_handoff_late: bool
    late_seller_ids: list[str]
    finding: str
    confidence: float


class PaymentReview(StrictModel):
    payment_row_count: int
    totals_reconciled: bool
    discrepancy_brl: float
    finding: str
    confidence: float


class DeliveryReview(StrictModel):
    delivered_after_estimate: bool
    delivery_timestamp_status: Literal["present", "missing"]
    finding: str
    confidence: float


class PolicyReview(StrictModel):
    primary_issue: PrimaryIssue = Field(
        description="The first matching issue in the supplied policy priority."
    )
    root_cause_code: CauseCode = Field(
        description="The one root-cause code mapped to primary_issue."
    )
    responsible_party_type: Literal[
        "seller", "platform", "logistics_provider", "none"
    ] = Field(description="Use none when policy assigns no responsible party.")
    responsible_party_ids: list[str] = Field(
        description=(
            "Exact IDs from authoritative handoffs; [] when party type is none."
        )
    )
    recommended_refund_brl: float = Field(
        description="Exact full payment, freight total, or zero required by policy."
    )
    action: ResolutionAction = Field(
        description="The action mapped to the selected primary issue."
    )
    finding: str = Field(description="Concise evidence-based decision summary.")
    confidence: float = Field(description="Confidence between 0 and 1.")
