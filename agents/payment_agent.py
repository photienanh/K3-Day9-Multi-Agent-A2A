from decimal import Decimal

from agents.base_agent import BaseAgent
from core.agent_schemas import PaymentAnalysis
from core.llm_client import LLMClient
from core.prompt_loader import load_prompt


class PaymentAgent(BaseAgent):
    def __init__(self, llm_client: LLMClient):
        super().__init__(
            "Payment Agent",
            "Reconcile payments with item and freight costs using gpt-4o-mini",
        )
        self.llm_client = llm_client

    def process(self, context: dict) -> dict:
        payments = context.get("payments", [])
        items = context.get("items", [])

        total_payment = sum(Decimal(str(p.get("payment_value", 0))) for p in payments)
        total_item = sum(Decimal(str(i.get("price", 0))) for i in items)
        total_freight = sum(Decimal(str(i.get("freight_value", 0))) for i in items)

        trusted_arithmetic = {
            "total_payment_brl": float(total_payment),
            "total_item_brl": float(total_item),
            "total_freight_brl": float(total_freight),
            "expected_total_brl": float(total_item + total_freight),
            "absolute_difference_brl": float(abs(total_payment - total_item - total_freight)),
        }
        result, llm_trace = self.llm_client.parse_structured(
            agent_name=self.name,
            system_prompt=load_prompt("payment_agent.md"),
            payload={
                "payments": payments,
                "items": [
                    {
                        "order_item_id": item.get("order_item_id"),
                        "price": item.get("price"),
                        "freight_value": item.get("freight_value"),
                    }
                    for item in items
                ],
                "trusted_arithmetic": trusted_arithmetic,
            },
            response_model=PaymentAnalysis,
        )

        # Arithmetic remains deterministic; GPT performs the domain interpretation.
        for key in ("total_payment_brl", "total_item_brl", "total_freight_brl"):
            result[key] = trusted_arithmetic[key]
        result["payment_count"] = len(payments)
        result["has_split_payment"] = len(payments) >= 2
        result["payment_matches_order"] = trusted_arithmetic["absolute_difference_brl"] <= 0.10

        source_sequences = sorted(int(p["payment_sequential"]) for p in payments)
        returned_sequences = sorted(int(p["payment_sequential"]) for p in result["payment_rows"])
        if returned_sequences != source_sequences:
            raise ValueError("Payment Agent returned payment IDs outside source data")

        result["_llm"] = llm_trace
        return result
