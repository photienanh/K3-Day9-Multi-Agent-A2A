from agents.base_agent import BaseAgent

class DeliveryAgent(BaseAgent):
    def __init__(self):
        super().__init__("Delivery Agent", "Compare actual delivery time with estimate")

    def process(self, context: dict) -> dict:
        order_info = context.get("order_info")
        items = context.get("items", [])
        
        if not order_info:
            return {}

        delivered_customer_date = order_info.get("order_delivered_customer_date")
        estimated_delivery_date = order_info.get("order_estimated_delivery_date")
        delivered_carrier_date = order_info.get("order_delivered_carrier_date")

        # Determine late delivery based on customer received date
        is_late_delivery = False
        if delivered_customer_date and estimated_delivery_date:
            is_late_delivery = delivered_customer_date > estimated_delivery_date
        elif not delivered_customer_date and estimated_delivery_date:
            # If not delivered yet but past estimate, we can consider it late or just use order status.
            pass

        seller_shipping_limits = []
        late_cause = "none"

        for item in items:
            shipping_limit = item.get("shipping_limit_date")
            seller_id = item.get("seller_id")
            carrier_pickup_late = False
            
            if delivered_carrier_date and shipping_limit:
                carrier_pickup_late = delivered_carrier_date > shipping_limit
            
            seller_shipping_limits.append({
                "seller_id": seller_id,
                "shipping_limit_date": shipping_limit,
                "carrier_pickup_late": carrier_pickup_late
            })
        
        # If it's a late delivery, determine cause
        if is_late_delivery:
            if any(s.get("carrier_pickup_late") for s in seller_shipping_limits):
                late_cause = "seller"
            else:
                late_cause = "logistics"

        result = {
            "order_delivered_customer_date": delivered_customer_date,
            "order_estimated_delivery_date": estimated_delivery_date,
            "is_late_delivery": is_late_delivery,
            "order_delivered_carrier_date": delivered_carrier_date,
            "seller_shipping_limits": seller_shipping_limits,
            "late_cause": late_cause
        }
        return result
