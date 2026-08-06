from agents.base_agent import BaseAgent
from core.agent_schemas import DeliveryAnalysis
from core.llm_client import LLMClient
from core.prompt_loader import load_prompt


class DeliveryAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Delivery Agent",
            "Determine late delivery and attribution using gpt-4o-mini",
        )
        self.llm_client = llm_client

    @staticmethod
    def _is_after(left, right) -> bool:
        return bool(left and right and left > right)

    def process(self, context: dict) -> dict:
        order_info = context.get("order_info") or {}
        items = context.get("items", [])
        delivered_customer = order_info.get("order_delivered_customer_date")
        estimated = order_info.get("order_estimated_delivery_date")
        delivered_carrier = order_info.get("order_delivered_carrier_date")

        comparison_facts = {
            "customer_delivery_after_estimate": self._is_after(
                delivered_customer, estimated
            ),
            "seller_shipping_limits": [
                {
                    "seller_id": item.get("seller_id"),
                    "shipping_limit_date": item.get("shipping_limit_date"),
                    "carrier_pickup_late": self._is_after(
                        delivered_carrier, item.get("shipping_limit_date")
                    ),
                }
                for item in items
            ],
        }

        result, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=load_prompt("delivery_agent.md"),
            payload={
                "order_timestamps": {
                    "order_delivered_customer_date": delivered_customer,
                    "order_estimated_delivery_date": estimated,
                    "order_delivered_carrier_date": delivered_carrier,
                },
                "comparison_facts": comparison_facts,
            },
            response_model=DeliveryAnalysis,
        )

        # Preserve exact source timestamps and comparison facts in the handoff.
        result["order_delivered_customer_date"] = delivered_customer
        result["order_estimated_delivery_date"] = estimated
        result["order_delivered_carrier_date"] = delivered_carrier
        result["seller_shipping_limits"] = comparison_facts["seller_shipping_limits"]

        expected_late = comparison_facts["customer_delivery_after_estimate"]
        if result["is_late_delivery"] != expected_late:
            raise ValueError("Delivery Agent contradicted the supplied date comparison")

        result["_llm"] = llm_trace
        return result
