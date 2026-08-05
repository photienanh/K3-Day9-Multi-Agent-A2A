from agents.base_agent import BaseAgent


class EvidenceAgent(BaseAgent):
    """Select evidence that supports both the policy decision and reported totals."""

    def __init__(self):
        super().__init__(
            "Evidence Agent",
            "Build a minimal, ordered evidence set from verified specialist outputs",
        )

    def process(self, context: dict) -> dict:
        order_id = context["order_id"]
        order_info = context.get("order_seller", {})
        payment_info = context.get("payment", {})
        policy_info = context.get("policy", {})

        evidence_ids = [f"order:{order_id}"]

        # Item rows substantiate the item/freight totals reported in every case
        # where such rows exist. Unavailable cases naturally have no item rows.
        for item in order_info.get("items", []):
            evidence_ids.append(f"item:{order_id}:{item['order_item_id']}")

        # Every payment row participates in payment_total_brl and, depending on
        # the rule, refund eligibility or split-payment reconciliation.
        for payment in payment_info.get("payment_rows", []):
            evidence_ids.append(
                f"payment:{order_id}:{payment['payment_sequential']}"
            )

        # A seller record is relevant evidence only when that seller is the
        # responsible party. Other seller IDs remain affected entities, but do
        # not become evidence for an unrelated conclusion.
        if policy_info.get("responsible_party_type") == "seller":
            seller_id = policy_info.get("responsible_party_id")
            if seller_id:
                evidence_ids.append(f"seller:{seller_id}")

        root_cause = policy_info.get("root_cause_code")
        if root_cause:
            evidence_ids.append(f"policy:{root_cause}")

        return {
            "evidence_ids": evidence_ids,
            "selection_basis": "policy_and_reported_financials",
        }
