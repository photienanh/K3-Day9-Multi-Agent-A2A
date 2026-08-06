from agents.base_agent import BaseAgent
from core.agent_schemas import VerifierAudit
from core.llm_client import LLMClient
from core.prompt_loader import load_prompt
from core.schemas import OutputSchema


class VerifierAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Verifier Agent",
            "Audit semantic consistency with gpt-4o-mini and validate constraints",
        )
        self.llm_client = llm_client

    def process(self, data: dict) -> dict:
        data["evidence_ids"] = data.get("evidence_ids", [])[:10]
        data["resolution_actions"] = data.get("resolution_actions", [])[:5]

        if "affected_entities" in data:
            for key in ("order_ids", "item_ids", "seller_ids", "payment_ids"):
                data["affected_entities"][key] = data["affected_entities"].get(key, [])[:5]

        if "root_cause_analysis" in data:
            data["root_cause_analysis"]["ranked_causes"] = data[
                "root_cause_analysis"
            ].get("ranked_causes", [])[:3]
            data["root_cause_analysis"]["responsible_parties"] = data[
                "root_cause_analysis"
            ].get("responsible_parties", [])[:3]

        if "financial_resolution" in data:
            for key in (
                "item_total_brl",
                "freight_total_brl",
                "payment_total_brl",
                "recommended_refund_brl",
            ):
                if key in data["financial_resolution"]:
                    data["financial_resolution"][key] = round(
                        data["financial_resolution"][key], 2
                    )

        refund = data.get("financial_resolution", {}).get("recommended_refund_brl", 0)
        data["assessment"]["case_status"] = (
            "action_required" if refund > 0 else "no_action"
        )
        confidence = data.get("assessment", {}).get("confidence", 1.0)
        data["assessment"]["confidence"] = max(0.0, min(1.0, confidence))

        try:
            validated = OutputSchema(**data).model_dump()
        except Exception as exc:
            return {"valid": False, "error": str(exc), "data": data}

        audit, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=load_prompt("verifier_agent.md"),
            payload={
                "candidate_output": validated,
                "constraints": {
                    "confidence_range": [0, 1],
                    "positive_refund_status": "action_required",
                    "zero_refund_status": "no_action",
                    "currency": "BRL",
                },
            },
            response_model=VerifierAudit,
        )
        return {
            "valid": True,
            "data": validated,
            "semantic_audit": audit,
            "audit_advisory_only": True,
            "_llm": llm_trace,
        }
