"""LangGraph nodes implementing domain handoffs, policy review, and verification."""

from __future__ import annotations

import operator
import time
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .llm import StructuredModelClient
from .policy import (
    build_case_output,
    evaluate_policy,
    policy_model_projection,
    verify_case_output,
)
from .schemas import (
    DeliveryReview,
    OrderSellerReview,
    PaymentReview,
    PolicyReview,
)
from .tracing import TraceCollector


COORDINATOR = "Coordinator Agent"
ORDER_SELLER_AGENT = "Order & Seller Agent"
PAYMENT_AGENT = "Payment Agent"
DELIVERY_AGENT = "Delivery Agent"
POLICY_AGENT = "Policy Agent"
VERIFIER_AGENT = "Verifier Agent"


class CaseState(TypedDict, total=False):
    case: dict[str, Any]
    facts: dict[str, Any]
    dispatched: bool
    completed_domains: Annotated[list[str], operator.add]
    order_analysis: dict[str, Any]
    payment_analysis: dict[str, Any]
    delivery_analysis: dict[str, Any]
    policy_decision: dict[str, Any]
    policy_analysis: dict[str, Any]
    draft_output: dict[str, Any]
    final_output: dict[str, Any]
    verification: dict[str, Any]


class MultiAgentGraph:
    """One compiled graph reused for every independent case."""

    def __init__(self, model: StructuredModelClient, trace: TraceCollector) -> None:
        self.model = model
        self.trace = trace
        builder = StateGraph(CaseState)
        builder.add_node("coordinator_agent", self.coordinator_agent)
        builder.add_node("order_seller_agent", self.order_seller_agent)
        builder.add_node("payment_agent", self.payment_agent)
        builder.add_node("delivery_agent", self.delivery_agent)
        builder.add_node("policy_agent", self.policy_agent)
        builder.add_node("verifier_agent", self.verifier_agent)
        builder.add_edge(START, "coordinator_agent")
        builder.add_edge("verifier_agent", END)
        self.graph = builder.compile(name="olist_dispute_multi_agent")

    @staticmethod
    def _identity(state: CaseState) -> tuple[str, str]:
        return (
            state["case"]["case_id"],
            state["facts"]["order"]["order_id"],
        )

    async def _agent_started(
        self,
        state: CaseState,
        *,
        agent: str,
        node: str,
        from_agent: str,
    ) -> float:
        case_id, order_id = self._identity(state)
        await self.trace.emit(
            "agent_started",
            case_id=case_id,
            order_id=order_id,
            agent=agent,
            node=node,
            handoff={"from": from_agent, "to": agent},
        )
        return time.perf_counter()

    async def _agent_completed(
        self,
        state: CaseState,
        *,
        agent: str,
        node: str,
        started: float,
        result: dict[str, Any],
        to_agent: str | list[str] | None,
    ) -> None:
        case_id, order_id = self._identity(state)
        duration_ms = round((time.perf_counter() - started) * 1000)
        await self.trace.emit(
            "agent_completed",
            case_id=case_id,
            order_id=order_id,
            agent=agent,
            node=node,
            duration_ms=duration_ms,
            details={"result": result},
        )
        if to_agent is not None:
            await self.trace.emit(
                "handoff",
                case_id=case_id,
                order_id=order_id,
                agent=agent,
                node=node,
                handoff={"from": agent, "to": to_agent},
                details={"payload_keys": sorted(result.keys())},
            )

    async def _agent_failed(
        self,
        state: CaseState,
        *,
        agent: str,
        node: str,
        started: float,
        exc: BaseException,
    ) -> None:
        case_id, order_id = self._identity(state)
        await self.trace.emit(
            "agent_failed",
            case_id=case_id,
            order_id=order_id,
            agent=agent,
            node=node,
            status="error",
            duration_ms=round((time.perf_counter() - started) * 1000),
            details={"error_type": type(exc).__name__, "message": str(exc)},
        )

    async def coordinator_agent(
        self, state: CaseState
    ) -> Command[
        Literal[
            "order_seller_agent",
            "payment_agent",
            "delivery_agent",
            "policy_agent",
            "verifier_agent",
        ]
    ]:
        case_id, order_id = self._identity(state)
        if not state.get("dispatched"):
            node = "coordinator_dispatch"
            started = await self._agent_started(
                state, agent=COORDINATOR, node=node, from_agent="START"
            )
            result = {
                "case_id": case_id,
                "order_id": order_id,
                "policy_version": state["case"]["policy_version"],
                "assigned_domains": ["order_seller", "payment", "delivery"],
            }
            await self._agent_completed(
                state,
                agent=COORDINATOR,
                node=node,
                started=started,
                result=result,
                to_agent=[ORDER_SELLER_AGENT, PAYMENT_AGENT, DELIVERY_AGENT],
            )
            return Command(
                update={"dispatched": True},
                goto=[
                    "order_seller_agent",
                    "payment_agent",
                    "delivery_agent",
                ],
            )

        required_domains = {"order_seller", "payment", "delivery"}
        completed_domains = set(state.get("completed_domains", []))
        if not required_domains.issubset(completed_domains):
            raise RuntimeError(
                f"{case_id}: coordinator resumed before fan-in completed: "
                f"{sorted(completed_domains)}"
            )

        if "policy_analysis" not in state:
            node = "coordinator_fan_in"
            started = await self._agent_started(
                state,
                agent=COORDINATOR,
                node=node,
                from_agent="domain_agents",
            )
            result = {
                "received_domains": sorted(completed_domains),
                "handoff_integrity": all(
                    key in state
                    for key in (
                        "order_analysis",
                        "payment_analysis",
                        "delivery_analysis",
                    )
                ),
            }
            await self._agent_completed(
                state,
                agent=COORDINATOR,
                node=node,
                started=started,
                result=result,
                to_agent=POLICY_AGENT,
            )
            return Command(goto="policy_agent")

        node = "coordinator_resolution"
        started = await self._agent_started(
            state, agent=COORDINATOR, node=node, from_agent=POLICY_AGENT
        )
        try:
            expected_projection = policy_model_projection(state["policy_decision"])
            model_projection = {
                key: state["policy_analysis"]["model_review"][key]
                for key in expected_projection
            }
            alignment = {
                key: model_projection[key] == expected_projection[key]
                for key in expected_projection
            }
            model_aligned = all(alignment.values())
            draft = build_case_output(
                state["facts"], state["policy_decision"]
            ).model_dump(mode="json")
            result = {
                "model_aligned_with_policy_oracle": model_aligned,
                "field_alignment": alignment,
                "resolution_method": (
                    "model_handoff_confirmed_by_deterministic_oracle"
                    if model_aligned
                    else "deterministic_override_after_model_disagreement"
                ),
                "draft_output": draft,
            }
            await self._agent_completed(
                state,
                agent=COORDINATOR,
                node=node,
                started=started,
                result=result,
                to_agent=VERIFIER_AGENT,
            )
            return Command(update={"draft_output": draft}, goto="verifier_agent")
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=COORDINATOR,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def order_seller_agent(
        self, state: CaseState
    ) -> Command[Literal["coordinator_agent"]]:
        node = "order_seller_agent"
        started = await self._agent_started(
            state, agent=ORDER_SELLER_AGENT, node=node, from_agent=COORDINATOR
        )
        case_id, order_id = self._identity(state)
        facts = state["facts"]
        payload = {
            "case_id": case_id,
            "order": facts["order"],
            "items": [
                {
                    key: item[key]
                    for key in (
                        "order_item_id",
                        "seller_id",
                        "shipping_limit_date",
                    )
                }
                for item in facts["items"]
            ],
        }
        instructions = (
            "You are the Order & Seller Agent. Audit only order status and seller "
            "handoff timing. Compare order_delivered_carrier_date with every "
            "shipping_limit_date; equality is on time. If a timestamp is missing, "
            "do not invent it. Return concise facts, not a refund decision."
        )
        try:
            model_review = await self.model.parse(
                agent=ORDER_SELLER_AGENT,
                node=node,
                case_id=case_id,
                order_id=order_id,
                instructions=instructions,
                payload=payload,
                schema=OrderSellerReview,
            )
            analysis = {
                "deterministic": {
                    "order_status": facts["order"]["order_status"],
                    "seller_handoff_late": bool(facts["late_seller_ids"]),
                    "late_seller_ids": facts["late_seller_ids"],
                    "item_count": len(facts["items"]),
                },
                "model_review": model_review,
            }
            analysis["model_alignment"] = {
                "order_status": model_review["order_status"]
                == analysis["deterministic"]["order_status"],
                "seller_handoff_late": model_review["seller_handoff_late"]
                == analysis["deterministic"]["seller_handoff_late"],
                "late_seller_ids": model_review["late_seller_ids"]
                == analysis["deterministic"]["late_seller_ids"],
            }
            await self._agent_completed(
                state,
                agent=ORDER_SELLER_AGENT,
                node=node,
                started=started,
                result=analysis,
                to_agent=COORDINATOR,
            )
            return Command(
                update={
                    "order_analysis": analysis,
                    "completed_domains": ["order_seller"],
                },
                goto="coordinator_agent",
            )
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=ORDER_SELLER_AGENT,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def payment_agent(
        self, state: CaseState
    ) -> Command[Literal["coordinator_agent"]]:
        node = "payment_agent"
        started = await self._agent_started(
            state, agent=PAYMENT_AGENT, node=node, from_agent=COORDINATOR
        )
        case_id, order_id = self._identity(state)
        facts = state["facts"]
        payload = {
            "case_id": case_id,
            "item_amounts": [
                {
                    "order_item_id": item["order_item_id"],
                    "price_brl": item["price_brl"],
                    "freight_brl": item["freight_brl"],
                }
                for item in facts["items"]
            ],
            "payment_rows": facts["payments"],
            "reconciliation_tolerance_brl": 0.10,
        }
        instructions = (
            "You are the Payment Agent. Sum each payment_value row exactly once; "
            "payment_installments is descriptive and must never multiply the value. "
            "Compare payment total with item price plus freight using <=0.10 BRL "
            "absolute tolerance. Do not decide responsibility or refund policy."
        )
        try:
            model_review = await self.model.parse(
                agent=PAYMENT_AGENT,
                node=node,
                case_id=case_id,
                order_id=order_id,
                instructions=instructions,
                payload=payload,
                schema=PaymentReview,
            )
            analysis = {
                "deterministic": facts["totals"],
                "model_review": model_review,
            }
            analysis["model_alignment"] = {
                "payment_row_count": model_review["payment_row_count"]
                == facts["totals"]["payment_row_count"],
                "totals_reconciled": model_review["totals_reconciled"]
                == facts["totals"]["totals_reconciled"],
                "discrepancy_brl": abs(
                    model_review["discrepancy_brl"]
                    - float(facts["totals"]["discrepancy_brl"])
                )
                <= 0.01,
            }
            await self._agent_completed(
                state,
                agent=PAYMENT_AGENT,
                node=node,
                started=started,
                result=analysis,
                to_agent=COORDINATOR,
            )
            return Command(
                update={
                    "payment_analysis": analysis,
                    "completed_domains": ["payment"],
                },
                goto="coordinator_agent",
            )
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=PAYMENT_AGENT,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def delivery_agent(
        self, state: CaseState
    ) -> Command[Literal["coordinator_agent"]]:
        node = "delivery_agent"
        started = await self._agent_started(
            state, agent=DELIVERY_AGENT, node=node, from_agent=COORDINATOR
        )
        case_id, order_id = self._identity(state)
        facts = state["facts"]
        payload = {
            "case_id": case_id,
            "order_id": order_id,
            "order_delivered_customer_date": facts["order"][
                "order_delivered_customer_date"
            ],
            "order_estimated_delivery_date": facts["order"][
                "order_estimated_delivery_date"
            ],
        }
        instructions = (
            "You are the Delivery Agent. Compare the actual customer delivery "
            "timestamp with the estimated delivery timestamp exactly as supplied, "
            "without timezone conversion. Delivery is late only when actual is "
            "strictly later. Missing actual delivery is not proof of late delivery."
        )
        try:
            model_review = await self.model.parse(
                agent=DELIVERY_AGENT,
                node=node,
                case_id=case_id,
                order_id=order_id,
                instructions=instructions,
                payload=payload,
                schema=DeliveryReview,
            )
            analysis = {
                "deterministic": facts["delivery"],
                "model_review": model_review,
            }
            analysis["model_alignment"] = {
                "delivered_after_estimate": model_review[
                    "delivered_after_estimate"
                ]
                == facts["delivery"]["delivered_after_estimate"],
                "delivery_timestamp_status": model_review[
                    "delivery_timestamp_status"
                ]
                == (
                    "present"
                    if facts["delivery"]["delivery_timestamp_present"]
                    else "missing"
                ),
            }
            await self._agent_completed(
                state,
                agent=DELIVERY_AGENT,
                node=node,
                started=started,
                result=analysis,
                to_agent=COORDINATOR,
            )
            return Command(
                update={
                    "delivery_analysis": analysis,
                    "completed_domains": ["delivery"],
                },
                goto="coordinator_agent",
            )
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=DELIVERY_AGENT,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def policy_agent(
        self, state: CaseState
    ) -> Command[Literal["coordinator_agent"]]:
        node = "policy_agent"
        started = await self._agent_started(
            state, agent=POLICY_AGENT, node=node, from_agent=COORDINATOR
        )
        case_id, order_id = self._identity(state)
        decision = evaluate_policy(state["facts"])
        payload = {
            "case_id": case_id,
            "policy_version": state["case"]["policy_version"],
            "verified_domain_handoffs": {
                "order_seller": state["order_analysis"]["deterministic"],
                "payment": state["payment_analysis"]["deterministic"],
                "delivery": state["delivery_analysis"]["deterministic"],
            },
            "domain_model_audit_alignment": {
                "order_seller": state["order_analysis"]["model_alignment"],
                "payment": state["payment_analysis"]["model_alignment"],
                "delivery": state["delivery_analysis"]["model_alignment"],
            },
            "decision_to_audit": policy_model_projection(decision),
        }
        instructions = (
            "You are the Policy Agent auditing EC_POLICY_V1. The deterministic policy "
            "engine has already applied the required first-match order to the verified "
            "domain handoffs. Check decision_to_audit for consistency, then copy its "
            "primary_issue, root_cause_code, responsible_party_type, "
            "responsible_party_ids, recommended_refund_brl, and action EXACTLY into "
            "your response. You may author only finding and confidence. Do not perform "
            "an independent reclassification and do not substitute a later policy rule."
        )
        try:
            model_review = await self.model.parse(
                agent=POLICY_AGENT,
                node=node,
                case_id=case_id,
                order_id=order_id,
                instructions=instructions,
                payload=payload,
                schema=PolicyReview,
            )
            analysis = {
                "deterministic_policy_oracle": decision,
                "model_review": model_review,
            }
            await self._agent_completed(
                state,
                agent=POLICY_AGENT,
                node=node,
                started=started,
                result=analysis,
                to_agent=COORDINATOR,
            )
            return Command(
                update={"policy_decision": decision, "policy_analysis": analysis},
                goto="coordinator_agent",
            )
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=POLICY_AGENT,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def verifier_agent(self, state: CaseState) -> dict[str, Any]:
        node = "verifier_agent"
        started = await self._agent_started(
            state, agent=VERIFIER_AGENT, node=node, from_agent=COORDINATOR
        )
        try:
            checks = verify_case_output(state["draft_output"], state["facts"])
            result = {
                "checks": checks,
                "write_authorized": True,
                "final_output": state["draft_output"],
            }
            await self._agent_completed(
                state,
                agent=VERIFIER_AGENT,
                node=node,
                started=started,
                result=result,
                to_agent=None,
            )
            return {
                "verification": checks,
                "final_output": state["draft_output"],
            }
        except BaseException as exc:
            await self._agent_failed(
                state,
                agent=VERIFIER_AGENT,
                node=node,
                started=started,
                exc=exc,
            )
            raise

    async def run_case(
        self, case: dict[str, Any], facts: dict[str, Any]
    ) -> dict[str, Any]:
        state = await self.graph.ainvoke(
            {
                "case": case,
                "facts": facts,
                "completed_domains": [],
            },
            config={"recursion_limit": 20},
        )
        if "final_output" not in state:
            raise RuntimeError(f"{case['case_id']}: graph ended without final output")
        return state["final_output"]
