from agents.base_agent import BaseAgent

class OrderSellerAgent(BaseAgent):
    def __init__(self):
        super().__init__("Order & Seller Agent", "Inspect order status, items, and seller shipping limits")

    def process(self, context: dict) -> dict:
        order_info = context.get("order_info")
        items = context.get("items", [])
        
        result = {
            "order_status": order_info.get("order_status") if order_info else None,
            "order_id": order_info.get("order_id") if order_info else None,
            "has_items": len(items) > 0,
            "items": [],
            "seller_ids": [],
            "order_delivered_carrier_date": order_info.get("order_delivered_carrier_date") if order_info else None
        }

        seller_ids = set()
        # Entity IDs are sets semantically, but keeping a canonical order makes
        # outputs and traces reproducible (and avoids depending on CSV row order).
        sorted_items = sorted(items, key=lambda item: int(item.get("order_item_id", 0)))
        for item in sorted_items:
            item_data = {
                "order_item_id": item.get("order_item_id"),
                "product_id": item.get("product_id"),
                "seller_id": item.get("seller_id"),
                "shipping_limit_date": item.get("shipping_limit_date"),
                "price": float(item.get("price", 0)),
                "freight_value": float(item.get("freight_value", 0))
            }
            result["items"].append(item_data)
            if item.get("seller_id"):
                seller_ids.add(item.get("seller_id"))
        
        result["seller_ids"] = sorted(seller_ids)
        return result
