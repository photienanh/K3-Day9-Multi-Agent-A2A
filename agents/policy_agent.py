from agents.base_agent import BaseAgent
from core.llm_client import LLMClient

class PolicyAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__("Policy Agent", "Apply business rules to determine refund and action")
        self.llm_client = llm_client

    def process(self, context: dict) -> dict:
        order_info = context.get("order_seller", {})
        payment_info = context.get("payment", {})
        delivery_info = context.get("delivery", {})
        
        order_status = order_info.get("order_status")
        total_payment = payment_info.get("total_payment_brl", 0)
        total_freight = payment_info.get("total_freight_brl", 0)
        
        is_late = delivery_info.get("is_late_delivery", False)
        late_cause = delivery_info.get("late_cause", "none")
        payment_matches = payment_info.get("payment_matches_order", False)
        has_split = payment_info.get("has_split_payment", False)

        result = {}

        # 1. canceled_order_paid
        if order_status == "canceled" and total_payment > 0:
            result = {
                "primary_issue": "canceled_order_paid",
                "root_cause_code": "ORDER_CANCELED_AFTER_PAYMENT",
                "responsible_party_type": "platform",
                "responsible_party_id": "OLIST_PLATFORM",
                "recommended_refund_brl": total_payment,
                "resolution_actions": ["issue_full_refund"]
            }
        # 2. unavailable_order_paid
        elif order_status == "unavailable" and total_payment > 0:
            result = {
                "primary_issue": "unavailable_order_paid",
                "root_cause_code": "ORDER_UNAVAILABLE_AFTER_PAYMENT",
                "responsible_party_type": "platform",
                "responsible_party_id": "OLIST_PLATFORM",
                "recommended_refund_brl": total_payment,
                "resolution_actions": ["issue_full_refund"]
            }
        # 3. late_delivery_seller
        elif is_late and late_cause == "seller":
            # Find the responsible seller(s). If multiple, just pick the first one that is late, or list all.
            # For simplicity per rules, we pick the first one that is late.
            responsible_seller = None
            for limit in delivery_info.get("seller_shipping_limits", []):
                if limit.get("carrier_pickup_late"):
                    responsible_seller = limit.get("seller_id")
                    break
            
            result = {
                "primary_issue": "late_delivery_seller",
                "root_cause_code": "SELLER_HANDOFF_AFTER_LIMIT",
                "responsible_party_type": "seller",
                "responsible_party_id": responsible_seller or "unknown",
                "recommended_refund_brl": total_freight,
                "resolution_actions": ["refund_freight"]
            }
        # 4. late_delivery_logistics
        elif is_late and late_cause == "logistics":
            result = {
                "primary_issue": "late_delivery_logistics",
                "root_cause_code": "CARRIER_DELIVERED_AFTER_ESTIMATE",
                "responsible_party_type": "logistics_provider",
                "responsible_party_id": "LOGISTICS_PROVIDER",
                "recommended_refund_brl": total_freight,
                "resolution_actions": ["refund_freight"]
            }
        # 5. valid_split_payment
        elif has_split and payment_matches:
            result = {
                "primary_issue": "valid_split_payment",
                "root_cause_code": "MULTIPLE_PAYMENTS_RECONCILED",
                "responsible_party_type": None,
                "responsible_party_id": None,
                "recommended_refund_brl": 0.0,
                "resolution_actions": ["explain_valid_split_payment"]
            }
        # 6. unsupported_late_claim
        elif not is_late and payment_matches:
            result = {
                "primary_issue": "unsupported_late_claim",
                "root_cause_code": "DELIVERY_WITHIN_ESTIMATE",
                "responsible_party_type": None,
                "responsible_party_id": None,
                "recommended_refund_brl": 0.0,
                "resolution_actions": ["reject_late_refund"]
            }
        else:
            raise ValueError("Case does not match any EC_POLICY_V1 rule")

        # Case status
        if result["recommended_refund_brl"] > 0:
            result["case_status"] = "action_required"
        else:
            result["case_status"] = "no_action"
            
        # EC_POLICY_V1 is deterministic and every fact used above comes directly
        # from the supplied CSV files. Confidence must therefore be reproducible,
        # not sampled from an LLM independently of the decision.
        result["confidence"] = 1.0
            
        return result
