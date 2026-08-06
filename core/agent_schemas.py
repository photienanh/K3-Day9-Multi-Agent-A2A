from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoordinatorPlan(StrictModel):
    case_id: str
    claimed_order_id: str
    policy_version: str
    investigation_goal: str
    agents_to_run: list[
        Literal[
            "Order & Seller Agent",
            "Payment Agent",
            "Delivery Agent",
            "Policy Agent",
            "Evidence Agent",
            "Verifier Agent",
        ]
    ]


class OrderItemAnalysis(StrictModel):
    order_item_id: int
    product_id: Optional[str]
    seller_id: Optional[str]
    shipping_limit_date: Optional[str]
    price: float
    freight_value: float


class OrderSellerAnalysis(StrictModel):
    order_status: Optional[str]
    order_id: Optional[str]
    has_items: bool
    items: list[OrderItemAnalysis]
    seller_ids: list[str]
    order_delivered_carrier_date: Optional[str]
    analysis_summary: str


class PaymentRowAnalysis(StrictModel):
    payment_sequential: int
    payment_value: float


class PaymentAnalysis(StrictModel):
    payment_rows: list[PaymentRowAnalysis]
    total_payment_brl: float
    total_item_brl: float
    total_freight_brl: float
    payment_count: int
    payment_matches_order: bool
    has_split_payment: bool
    reconciliation_summary: str


class SellerShippingAnalysis(StrictModel):
    seller_id: Optional[str]
    shipping_limit_date: Optional[str]
    carrier_pickup_late: bool


class DeliveryAnalysis(StrictModel):
    order_delivered_customer_date: Optional[str]
    order_estimated_delivery_date: Optional[str]
    is_late_delivery: bool
    order_delivered_carrier_date: Optional[str]
    seller_shipping_limits: list[SellerShippingAnalysis]
    late_cause: Literal["seller", "logistics", "none"]
    analysis_summary: str


class PolicyRuleEvaluation(StrictModel):
    priority: int
    rule_name: Literal[
        "canceled_order_paid",
        "unavailable_order_paid",
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "unsupported_late_claim",
    ]
    matched: bool
    reason: str


class PolicyAnalysis(StrictModel):
    rule_evaluations: list[PolicyRuleEvaluation]
    primary_issue: Literal[
        "canceled_order_paid",
        "unavailable_order_paid",
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "unsupported_late_claim",
    ]
    root_cause_code: Literal[
        "ORDER_CANCELED_AFTER_PAYMENT",
        "ORDER_UNAVAILABLE_AFTER_PAYMENT",
        "SELLER_HANDOFF_AFTER_LIMIT",
        "CARRIER_DELIVERED_AFTER_ESTIMATE",
        "MULTIPLE_PAYMENTS_RECONCILED",
        "DELIVERY_WITHIN_ESTIMATE",
    ]
    responsible_party_type: Optional[
        Literal["platform", "seller", "logistics_provider"]
    ]
    responsible_party_id: Optional[str]
    recommended_refund_brl: float
    resolution_actions: list[
        Literal[
            "issue_full_refund",
            "refund_freight",
            "explain_valid_split_payment",
            "reject_late_refund",
        ]
    ]
    case_status: Literal["action_required", "no_action"]
    confidence: float
    decision_explanation: str


class EvidenceAnalysis(StrictModel):
    evidence_ids: list[str]
    selection_basis: Literal["policy_and_reported_financials"]
    selection_explanation: str


class VerifierAudit(StrictModel):
    semantic_valid: bool
    issues: list[str]
    audit_summary: str
