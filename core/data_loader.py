import pandas as pd
import os
from typing import Dict, Any

class DataLoader:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.orders = pd.DataFrame()
        self.order_items = pd.DataFrame()
        self.order_payments = pd.DataFrame()
        self.customers = pd.DataFrame()
        self.sellers = pd.DataFrame()
        self.products = pd.DataFrame()
        self._load_data()

    def _load_data(self):
        self.orders = pd.read_csv(os.path.join(self.data_dir, "olist_orders_dataset.csv"))
        self.order_items = pd.read_csv(os.path.join(self.data_dir, "olist_order_items_dataset.csv"))
        self.order_payments = pd.read_csv(os.path.join(self.data_dir, "olist_order_payments_dataset.csv"))
        self.customers = pd.read_csv(os.path.join(self.data_dir, "olist_customers_dataset.csv"))
        self.sellers = pd.read_csv(os.path.join(self.data_dir, "olist_sellers_dataset.csv"))
        self.products = pd.read_csv(os.path.join(self.data_dir, "olist_products_dataset.csv"))

    def get_order_context(self, order_id: str) -> Dict[str, Any]:
        context = {"order_id": order_id}

        # Order info
        order = self.orders[self.orders["order_id"] == order_id]
        if not order.empty:
            order_record = order.iloc[0].to_dict()
            # Handle NaN values
            order_record = {k: (v if pd.notna(v) else None) for k, v in order_record.items()}
            context["order_info"] = order_record
        else:
            context["order_info"] = None

        # Items info
        items = self.order_items[self.order_items["order_id"] == order_id]
        if not items.empty:
            items_list = items.to_dict(orient="records")
            items_list = [{k: (v if pd.notna(v) else None) for k, v in item.items()} for item in items_list]
            context["items"] = items_list
        else:
            context["items"] = []

        # Payments info
        payments = self.order_payments[self.order_payments["order_id"] == order_id]
        if not payments.empty:
            payments_list = payments.to_dict(orient="records")
            payments_list = [{k: (v if pd.notna(v) else None) for k, v in item.items()} for item in payments_list]
            context["payments"] = payments_list
        else:
            context["payments"] = []

        return context
