"""Independent validator for outputs, online trace, and metadata."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import (
    EXPECTED_CASE_COUNT,
    METADATA_PATH,
    MODEL_NAME,
    OUTPUT_DIR,
    PROJECT_ROOT,
    TRACE_PATH,
)
from .data_repository import DataRepository
from .policy import build_case_output, evaluate_policy, verify_case_output
from .schemas import CaseOutput


class ArtifactValidationError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"Cannot read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"Expected JSON object in {path}")
    return value


def load_trace(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ArtifactValidationError(
                        f"Blank line in trace at line {line_number}"
                    )
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ArtifactValidationError(
                        f"Trace line {line_number} is not an object"
                    )
                events.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(f"Invalid trace file {path}: {exc}") from exc
    if not events:
        raise ArtifactValidationError("Trace is empty")
    return events


def validate_outputs(repository: DataRepository) -> Counter[str]:
    expected_names = {f"{case['case_id']}.json" for case in repository.cases}
    actual_names = {path.name for path in OUTPUT_DIR.glob("*.json")}
    if actual_names != expected_names:
        raise ArtifactValidationError(
            f"Output file set mismatch; missing={sorted(expected_names-actual_names)}, "
            f"extra={sorted(actual_names-expected_names)}"
        )

    issue_counts: Counter[str] = Counter()
    for case in repository.cases:
        case_id = case["case_id"]
        facts = repository.facts_for_case(case)
        raw = load_json(OUTPUT_DIR / f"{case_id}.json")
        try:
            output = CaseOutput.model_validate(raw)
        except ValidationError as exc:
            raise ArtifactValidationError(f"{case_id}: output schema invalid") from exc
        verify_case_output(output, facts)
        expected = build_case_output(facts, evaluate_policy(facts))
        if output.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ArtifactValidationError(f"{case_id}: output differs from oracle")
        issue_counts[output.assessment.primary_issue] += 1
    return issue_counts


def validate_trace_and_metadata(
    repository: DataRepository, metadata: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_metadata_keys = {"model", "framework", "runtime", "policy", "agents"}
    if set(metadata) != expected_metadata_keys:
        raise ArtifactValidationError("metadata must use the compact submission schema")
    run_id = events[0].get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ArtifactValidationError("trace run_id is missing")
    if metadata.get("model", {}).get("name") != MODEL_NAME:
        raise ArtifactValidationError(f"metadata model must be {MODEL_NAME}")
    if metadata.get("model", {}).get("parameter_size") != "~8B":
        raise ArtifactValidationError("metadata parameter_size must be ~8B")
    if metadata.get("framework", {}).get("name") != "LangGraph":
        raise ArtifactValidationError("metadata framework must be LangGraph")
    if not metadata.get("runtime", {}).get("python"):
        raise ArtifactValidationError("metadata runtime.python is missing")
    if metadata.get("policy", {}).get("version") != "EC_POLICY_V1":
        raise ArtifactValidationError("metadata policy must be EC_POLICY_V1")
    expected_agents = {
        "Coordinator Agent",
        "Order & Seller Agent",
        "Payment Agent",
        "Delivery Agent",
        "Policy Agent",
        "Verifier Agent",
    }
    actual_agents = {agent.get("name") for agent in metadata.get("agents", [])}
    if actual_agents != expected_agents:
        raise ArtifactValidationError("metadata agent set is incomplete")

    if any(event.get("run_id") != run_id for event in events):
        raise ArtifactValidationError("Trace contains a different run_id")
    expected_sequences = list(range(1, len(events) + 1))
    actual_sequences = [event.get("sequence") for event in events]
    if actual_sequences != expected_sequences:
        raise ArtifactValidationError("Trace sequence is not contiguous")
    timestamps = [event.get("timestamp") for event in events]
    if timestamps != sorted(timestamps):
        raise ArtifactValidationError("Trace timestamps are not nondecreasing")
    if events[0].get("event") != "run_started":
        raise ArtifactValidationError("First trace event must be run_started")
    if events[-1].get("event") != "run_completed":
        raise ArtifactValidationError("Last trace event must be run_completed")
    failed_events = [
        event
        for event in events
        if event.get("status") == "error" or event.get("event", "").endswith("failed")
    ]
    if failed_events:
        raise ArtifactValidationError(f"Trace contains {len(failed_events)} errors")

    expected_case_ids = {case["case_id"] for case in repository.cases}
    completed_case_ids = {
        event.get("case_id")
        for event in events
        if event.get("event") == "case_completed"
    }
    if completed_case_ids != expected_case_ids:
        raise ArtifactValidationError("Trace case_completed set is not all 50 cases")
    if sum(event.get("event") == "case_completed" for event in events) != len(
        expected_case_ids
    ):
        raise ArtifactValidationError("Trace has duplicate case_completed events")

    required_nodes = {
        "coordinator_dispatch",
        "order_seller_agent",
        "payment_agent",
        "delivery_agent",
        "coordinator_fan_in",
        "policy_agent",
        "coordinator_resolution",
        "verifier_agent",
    }
    completed_nodes: dict[str, set[str]] = defaultdict(set)
    for event in events:
        if event.get("event") == "agent_completed":
            completed_nodes[event["case_id"]].add(event["node"])
    for case_id in expected_case_ids:
        if completed_nodes[case_id] != required_nodes:
            raise ArtifactValidationError(
                f"{case_id}: agent node coverage mismatch: {completed_nodes[case_id]}"
            )

    llm_responses = [event for event in events if event.get("event") == "llm_response"]
    expected_model_calls = EXPECTED_CASE_COUNT * 4
    if len(llm_responses) != expected_model_calls:
        raise ArtifactValidationError(
            f"Expected {expected_model_calls} model responses, got {len(llm_responses)}"
        )
    if any(
        event.get("details", {}).get("requested_model") != MODEL_NAME
        or not event.get("details", {}).get("response_id")
        or not event.get("details", {}).get("usage")
        for event in llm_responses
    ):
        raise ArtifactValidationError("A model response lacks model/id/usage metadata")
    total_tokens = sum(
        int(event["details"]["usage"].get("total_tokens") or 0)
        for event in llm_responses
    )
    if total_tokens <= 0:
        raise ArtifactValidationError("Trace total token usage is missing")
    return {
        "run_id": run_id,
        "model_calls": len(llm_responses),
        "total_tokens": total_tokens,
    }


def run_validation() -> dict[str, Any]:
    repository = DataRepository()
    if len(repository.cases) != EXPECTED_CASE_COUNT:
        raise ArtifactValidationError(
            f"Expected {EXPECTED_CASE_COUNT} cases, found {len(repository.cases)}"
        )
    issue_counts = validate_outputs(repository)
    metadata = load_json(METADATA_PATH)
    events = load_trace(TRACE_PATH)
    trace_summary = validate_trace_and_metadata(repository, metadata, events)

    architecture_path = PROJECT_ROOT / "architecture.md"
    report_paths = sorted(PROJECT_ROOT.glob("individual_*.md"))
    if not architecture_path.is_file() or architecture_path.stat().st_size == 0:
        raise ArtifactValidationError("architecture.md is missing or empty")
    if not report_paths:
        raise ArtifactValidationError("Individual report is missing")
    return {
        "status": "PASS",
        "cases": len(repository.cases),
        "outputs": len(list(OUTPUT_DIR.glob("*.json"))),
        "trace_events": len(events),
        "model_calls": trace_summary["model_calls"],
        "issue_counts": dict(sorted(issue_counts.items())),
        "run_id": trace_summary["run_id"],
    }


def main() -> int:
    try:
        result = run_validation()
    except BaseException as exc:
        print(f"VALIDATION FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
