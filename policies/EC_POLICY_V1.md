# EC_POLICY_V1

Apply the first matching rule in this exact priority order:

1. `canceled_order_paid`: order_status is `canceled` and total_payment_brl > 0.
   Root cause `ORDER_CANCELED_AFTER_PAYMENT`; responsible party `platform` / `OLIST_PLATFORM`;
   refund total_payment_brl; action `issue_full_refund`.
2. `unavailable_order_paid`: order_status is `unavailable` and total_payment_brl > 0.
   Root cause `ORDER_UNAVAILABLE_AFTER_PAYMENT`; responsible party `platform` / `OLIST_PLATFORM`;
   refund total_payment_brl; action `issue_full_refund`.
3. `late_delivery_seller`: delivery is late and late_cause is `seller`.
   Root cause `SELLER_HANDOFF_AFTER_LIMIT`; responsible party `seller` / the first seller whose
   carrier_pickup_late is true; refund total_freight_brl; action `refund_freight`.
4. `late_delivery_logistics`: delivery is late and late_cause is `logistics`.
   Root cause `CARRIER_DELIVERED_AFTER_ESTIMATE`; responsible party `logistics_provider` /
   `LOGISTICS_PROVIDER`; refund total_freight_brl; action `refund_freight`.
5. `valid_split_payment`: has_split_payment is true and payment_matches_order is true.
   Root cause `MULTIPLE_PAYMENTS_RECONCILED`; no responsible party; refund 0;
   action `explain_valid_split_payment`.
6. `unsupported_late_claim`: delivery is not late and payment_matches_order is true.
   Root cause `DELIVERY_WITHIN_ESTIMATE`; no responsible party; refund 0;
   action `reject_late_refund`.

Set `case_status` to `action_required` when the recommended refund is greater than zero;
otherwise set it to `no_action`.
