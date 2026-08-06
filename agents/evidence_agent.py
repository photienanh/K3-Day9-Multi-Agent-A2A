from agents.base_agent import BaseAgent
from core.agent_schemas import EvidenceAnalysis
from core.llm_client import LLMClient
from core.prompt_loader import load_prompt


class EvidenceAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Evidence Agent",
            "Select grounded evidence IDs using gpt-4o-mini",
        )
        self.llm_client = llm_client

    def process(self, context: dict) -> dict:
        order_id = context["order_id"]
        order_info = context.get("order_seller", {})
        payment_info = context.get("payment", {})
        policy_info = context.get("policy", {})

        allowed_evidence_ids = [f"order:{order_id}"]
        allowed_evidence_ids.extend(
            f"item:{order_id}:{item['order_item_id']}"
            for item in order_info.get("items", [])
        )
        allowed_evidence_ids.extend(
            f"payment:{order_id}:{payment['payment_sequential']}"
            for payment in payment_info.get("payment_rows", [])
        )
        if policy_info.get("responsible_party_type") == "seller":
            seller_id = policy_info.get("responsible_party_id")
            if seller_id:
                allowed_evidence_ids.append(f"seller:{seller_id}")
        root_cause = policy_info.get("root_cause_code")
        if root_cause:
            allowed_evidence_ids.append(f"policy:{root_cause}")

        result, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=load_prompt("evidence_agent.md"),
            payload={
                "allowed_evidence_ids": allowed_evidence_ids,
                "order_seller": order_info,
                "payment": payment_info,
                "policy": policy_info,
            },
            response_model=EvidenceAnalysis,
        )

        returned = result["evidence_ids"]
        if len(returned) != len(set(returned)):
            raise ValueError("Evidence Agent returned duplicate evidence IDs")
        if any(evidence_id not in allowed_evidence_ids for evidence_id in returned):
            raise ValueError("Evidence Agent returned an ID outside the grounded allowlist")

        # Keep the model selection in the trace and enforce the complete grounded set.
        # This is a safety/grounding guard, not a business-policy decision.
        result["model_selected_evidence_ids"] = returned
        result["grounding_adjusted"] = returned != allowed_evidence_ids
        result["evidence_ids"] = allowed_evidence_ids
        result["_llm"] = llm_trace
        return result
