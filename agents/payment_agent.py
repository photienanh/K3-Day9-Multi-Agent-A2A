from agents.base_agent import BaseAgent

class PaymentAgent(BaseAgent):
    def __init__(self):
        super().__init__("Payment Agent", "Reconcile payments with items and freight costs")

    def process(self, context: dict) -> dict:
        payments = context.get("payments", [])
        items = context.get("items", [])
        
        total_payment = sum(float(p.get("payment_value", 0)) for p in payments)
        total_item_price = sum(float(i.get("price", 0)) for i in items)
        total_freight = sum(float(i.get("freight_value", 0)) for i in items)
        expected_total = total_item_price + total_freight
        
        payment_matches_order = abs(total_payment - expected_total) <= 0.10
        has_split_payment = len(payments) >= 2

        sorted_payments = sorted(
            payments,
            key=lambda payment: int(payment.get("payment_sequential", 0)),
        )

        result = {
            "payment_rows": [{"payment_sequential": p.get("payment_sequential"), "payment_value": float(p.get("payment_value", 0))} for p in sorted_payments],
            "total_payment_brl": total_payment,
            "total_item_brl": total_item_price,
            "total_freight_brl": total_freight,
            "payment_count": len(payments),
            "payment_matches_order": payment_matches_order,
            "has_split_payment": has_split_payment
        }
        return result
