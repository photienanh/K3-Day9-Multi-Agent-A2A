from agents.base_agent import BaseAgent
from core.agent_schemas import PolicyAnalysis
from core.llm_client import LLMClient
from core.prompt_loader import load_policy, load_prompt


class PolicyAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Policy Agent",
            "Apply EC_POLICY_V1 with gpt-4o-mini structured reasoning",
        )
        self.llm_client = llm_client

    def process(self, context: dict) -> dict:
        system_prompt = (
            load_prompt("policy_agent.md")
            + "\n\nThe authoritative policy follows:\n\n"
            + load_policy()
        )
        result, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=system_prompt,
            payload=context,
            response_model=PolicyAnalysis,
        )

        evaluations = result.get("rule_evaluations", [])
        if len(evaluations) != 6 or [row["priority"] for row in evaluations] != list(
            range(1, 7)
        ):
            raise ValueError("Policy Agent did not evaluate all six rules in priority order")
        matched_rules = [row["rule_name"] for row in evaluations if row["matched"]]
        if not matched_rules or result["primary_issue"] != matched_rules[0]:
            raise ValueError("Policy Agent did not choose the first matching rule")

        payment = context.get("payment", {})
        refund = float(result["recommended_refund_brl"])
        max_supported_refund = max(
            float(payment.get("total_payment_brl", 0)),
            float(payment.get("total_freight_brl", 0)),
        )
        if refund < 0 or refund > max_supported_refund + 0.01:
            raise ValueError("Policy Agent returned a refund outside source financials")
        if (refund > 0) != (result["case_status"] == "action_required"):
            raise ValueError("Policy Agent returned inconsistent refund and case_status")

        # Preserve the raw model rating and apply only a general confidence bound.
        # Business-rule selection remains the model's decision.
        result["raw_model_confidence"] = result["confidence"]
        result["confidence"] = round(
            max(0.0, min(0.99, float(result["confidence"]))), 4
        )

        # Ground entity IDs to canonical identifiers after the model selects the party type.
        party_type = result.get("responsible_party_type")
        if party_type == "platform":
            result["responsible_party_id"] = "OLIST_PLATFORM"
        elif party_type == "logistics_provider":
            result["responsible_party_id"] = "LOGISTICS_PROVIDER"
        elif party_type == "seller":
            late_sellers = [
                row.get("seller_id")
                for row in context.get("delivery", {}).get("seller_shipping_limits", [])
                if row.get("carrier_pickup_late") and row.get("seller_id")
            ]
            if not late_sellers:
                raise ValueError("Policy Agent selected seller without a grounded late seller")
            result["responsible_party_id"] = late_sellers[0]
        else:
            result["responsible_party_id"] = None

        result["_llm"] = llm_trace
        return result
