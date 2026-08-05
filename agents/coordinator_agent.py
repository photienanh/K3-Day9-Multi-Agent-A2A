from agents.base_agent import BaseAgent
from agents.order_seller_agent import OrderSellerAgent
from agents.payment_agent import PaymentAgent
from agents.delivery_agent import DeliveryAgent
from agents.policy_agent import PolicyAgent
from agents.evidence_agent import EvidenceAgent
from agents.verifier_agent import VerifierAgent
from core.llm_client import LLMClient

class CoordinatorAgent(BaseAgent):
    def __init__(self, data_loader, llm_client: LLMClient):
        super().__init__("Coordinator Agent", "Coordinate the execution of sub-agents")
        self.data_loader = data_loader
        self.llm_client = llm_client
        
        self.order_seller_agent = OrderSellerAgent()
        self.payment_agent = PaymentAgent()
        self.delivery_agent = DeliveryAgent()
        self.policy_agent = PolicyAgent(llm_client)
        self.evidence_agent = EvidenceAgent()
        self.verifier_agent = VerifierAgent()

    def process(self, input_case: dict) -> tuple:
        case_id = input_case["case_id"]
        claimed_order_id = input_case["customer_request"]["claimed_order_id"]
        
        agent_traces = []
        
        # Load data context
        data_context = self.data_loader.get_order_context(claimed_order_id)
        
        # Run sub-agents
        order_res = self.order_seller_agent.process(data_context)
        agent_traces.append({"agent": self.order_seller_agent.name, "output": order_res})
        
        payment_res = self.payment_agent.process(data_context)
        agent_traces.append({"agent": self.payment_agent.name, "output": payment_res})
        
        delivery_res = self.delivery_agent.process(data_context)
        agent_traces.append({"agent": self.delivery_agent.name, "output": delivery_res})
        
        # Policy Agent
        policy_context = {
            "order_seller": order_res,
            "payment": payment_res,
            "delivery": delivery_res
        }
        policy_res = self.policy_agent.process(policy_context)
        agent_traces.append({"agent": self.policy_agent.name, "output": policy_res})
        
        # Construct Final Output Dictionary
        
        # Canonical entity IDs. The specialist agents already sort their rows,
        # so the same input always produces byte-for-byte stable lists.
        item_entity_ids = []
        for item in order_res.get("items", []):
            entity_id_str = f"{claimed_order_id}:{item['order_item_id']}"
            item_entity_ids.append(entity_id_str)
            
        payment_entity_ids = []
        for p in payment_res.get("payment_rows", []):
            entity_id_str = f"{claimed_order_id}:{p['payment_sequential']}"
            payment_entity_ids.append(entity_id_str)

        policy_cause = policy_res.get("root_cause_code")

        evidence_res = self.evidence_agent.process({
            "order_id": claimed_order_id,
            "order_seller": order_res,
            "payment": payment_res,
            "policy": policy_res,
        })
        agent_traces.append({"agent": self.evidence_agent.name, "output": evidence_res})
        evidence_ids = evidence_res["evidence_ids"]

        # Entities
        seller_ids = order_res.get("seller_ids", [])
        
        ranked_causes = []
        if policy_cause:
            ranked_causes.append({"cause_code": policy_cause, "rank": 1})
            
        responsible_parties = []
        if policy_res.get("responsible_party_type"):
            responsible_parties.append({
                "party_type": policy_res["responsible_party_type"],
                "party_id": policy_res["responsible_party_id"]
            })

        final_dict = {
            "case_id": case_id,
            "assessment": {
                "primary_issue": policy_res.get("primary_issue"),
                "case_status": policy_res.get("case_status"),
                "confidence": policy_res.get("confidence")
            },
            "affected_entities": {
                "order_ids": [claimed_order_id],
                "item_ids": item_entity_ids,
                "seller_ids": seller_ids,
                "payment_ids": payment_entity_ids
            },
            "root_cause_analysis": {
                "ranked_causes": ranked_causes,
                "responsible_parties": responsible_parties
            },
            "evidence_ids": evidence_ids,
            "financial_resolution": {
                "currency": "BRL",
                "item_total_brl": payment_res.get("total_item_brl", 0.0),
                "freight_total_brl": payment_res.get("total_freight_brl", 0.0),
                "payment_total_brl": payment_res.get("total_payment_brl", 0.0),
                "recommended_refund_brl": policy_res.get("recommended_refund_brl", 0.0)
            },
            "resolution_actions": policy_res.get("resolution_actions", [])
        }

        # Handle no items case
        if not order_res.get("has_items"):
            final_dict["affected_entities"]["item_ids"] = []
            final_dict["affected_entities"]["seller_ids"] = []
            final_dict["financial_resolution"]["item_total_brl"] = 0.0
            final_dict["financial_resolution"]["freight_total_brl"] = 0.0

        # Verifier Agent
        verify_res = self.verifier_agent.process(final_dict)
        agent_traces.append({"agent": self.verifier_agent.name, "output": verify_res})

        if not verify_res.get("valid"):
            raise ValueError(f"Verifier rejected {case_id}: {verify_res.get('error')}")

        return verify_res["data"], agent_traces
