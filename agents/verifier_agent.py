from agents.base_agent import BaseAgent
from core.schemas import OutputSchema
import json

class VerifierAgent(BaseAgent):
    def __init__(self):
        super().__init__("Verifier Agent", "Verify output schema and constraints")

    def process(self, data: dict) -> dict:
        # data is the final dictionary representing the output
        
        # 1. Truncate lists to limits
        data["evidence_ids"] = data.get("evidence_ids", [])[:10]
        data["resolution_actions"] = data.get("resolution_actions", [])[:5]
        
        if "affected_entities" in data:
            data["affected_entities"]["order_ids"] = data["affected_entities"].get("order_ids", [])[:5]
            data["affected_entities"]["item_ids"] = data["affected_entities"].get("item_ids", [])[:5]
            data["affected_entities"]["seller_ids"] = data["affected_entities"].get("seller_ids", [])[:5]
            data["affected_entities"]["payment_ids"] = data["affected_entities"].get("payment_ids", [])[:5]

        if "root_cause_analysis" in data:
            data["root_cause_analysis"]["ranked_causes"] = data["root_cause_analysis"].get("ranked_causes", [])[:3]
            data["root_cause_analysis"]["responsible_parties"] = data["root_cause_analysis"].get("responsible_parties", [])[:3]

        # 2. Round financials
        if "financial_resolution" in data:
            fr = data["financial_resolution"]
            for k in ["item_total_brl", "freight_total_brl", "payment_total_brl", "recommended_refund_brl"]:
                if k in fr:
                    fr[k] = round(fr[k], 2)

        # 3. Ensure case_status matches refund
        refund = data.get("financial_resolution", {}).get("recommended_refund_brl", 0)
        status = data.get("assessment", {}).get("case_status", "no_action")
        if refund > 0:
            data["assessment"]["case_status"] = "action_required"
        else:
            data["assessment"]["case_status"] = "no_action"
            
        # 4. Confidence bound
        conf = data.get("assessment", {}).get("confidence", 1.0)
        data["assessment"]["confidence"] = max(0.0, min(1.0, conf))
        
        # 5. Schema Validation
        try:
            OutputSchema(**data)
            return {"valid": True, "data": data}
        except Exception as e:
            return {"valid": False, "error": str(e), "data": data}
