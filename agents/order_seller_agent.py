from agents.base_agent import BaseAgent
from core.agent_schemas import OrderSellerAnalysis
from core.llm_client import LLMClient
from core.prompt_loader import load_prompt


class OrderSellerAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Order & Seller Agent",
            "Inspect order status, items, and seller shipping limits with gpt-4o-mini",
        )
        self.llm_client = llm_client

    def process(self, context: dict) -> dict:
        result, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=load_prompt("order_seller_agent.md"),
            payload={
                "order_info": context.get("order_info"),
                "items": context.get("items", []),
            },
            response_model=OrderSellerAnalysis,
        )

        expected_order_id = context.get("order_id")
        if result.get("order_id") not in (None, expected_order_id):
            raise ValueError(f"Order & Seller Agent changed order_id {expected_order_id}")

        source_item_ids = {
            int(item["order_item_id"])
            for item in context.get("items", [])
            if item.get("order_item_id") is not None
        }
        returned_item_ids = {int(item["order_item_id"]) for item in result["items"]}
        if returned_item_ids != source_item_ids:
            raise ValueError("Order & Seller Agent returned item IDs outside source data")

        result["_llm"] = llm_trace
        return result
