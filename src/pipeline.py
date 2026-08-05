"""CLI entrypoint for the 50-case online LangGraph run."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import MultiAgentGraph
from .config import (
    DATA_DIR,
    EXPECTED_CASE_COUNT,
    INPUT_DIR,
    LOGGING_DIR,
    METADATA_PATH,
    MODEL_NAME,
    MODEL_TEMPERATURE,
    OUTPUT_DIR,
    POLICY_VERSION,
    PROJECT_ROOT,
    TRACE_PATH,
    load_project_environment,
)
from .data_repository import DataRepository
from .llm import StructuredModelClient
from .policy import verify_case_output
from .tracing import TraceCollector, atomic_write_json, utc_now


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def input_collection_sha256(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_metadata(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    duration_ms: int,
    trace: TraceCollector,
    outputs: dict[str, dict[str, Any]],
    concurrency: int,
    llm_concurrency: int,
) -> dict[str, Any]:
    issue_counts = Counter(
        output["assessment"]["primary_issue"] for output in outputs.values()
    )
    response_models = sorted(
        {
            event["details"]["response_model"]
            for event in trace.events
            if event["event"] == "llm_response"
            and event.get("details", {}).get("response_model")
        }
    )
    source_paths = [
        DATA_DIR / "olist_orders_dataset.csv",
        DATA_DIR / "olist_order_items_dataset.csv",
        DATA_DIR / "olist_order_payments_dataset.csv",
        DATA_DIR / "olist_sellers_dataset.csv",
    ]
    input_paths = sorted(INPUT_DIR.glob("EC_*.json"))
    return {
        "schema_version": "1.0",
        "assignment": "K3 Day 09 - Multi-Agent E-commerce Dispute Resolution",
        "run_id": run_id,
        "generated_at": finished_at,
        "model": {
            "provider": "openai",
            "name": MODEL_NAME,
            "response_models_observed": response_models,
            "parameter_size": "not_publicly_disclosed",
            "parameter_limit_requirement": "<=10B",
            "parameter_compliance_note": (
                "OpenAI does not publicly disclose the parameter count for "
                "gpt-4o-mini; the requested model is recorded without inventing a size."
            ),
            "temperature": MODEL_TEMPERATURE,
            "structured_output": "native_json_schema_strict",
        },
        "framework": {
            "name": "LangGraph",
            "version": package_version("langgraph"),
            "integration": "langchain-openai",
            "integration_version": package_version("langchain-openai"),
            "graph_name": "olist_dispute_multi_agent",
            "routing": "Command handoff with parallel domain fan-out and coordinator fan-in",
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "openai_sdk": package_version("openai"),
            "pydantic": package_version("pydantic"),
            "python_dotenv": package_version("python-dotenv"),
            "entrypoint": ".venv/bin/python -m src.pipeline",
            "working_directory": str(PROJECT_ROOT),
        },
        "policy": {
            "version": POLICY_VERSION,
            "money_currency": "BRL",
            "money_rounding_decimals": 2,
            "payment_reconciliation_tolerance_brl": 0.10,
            "decision_mode": "first_match_priority",
        },
        "agents": [
            {
                "name": "Coordinator Agent",
                "nodes": [
                    "coordinator_dispatch",
                    "coordinator_fan_in",
                    "coordinator_resolution",
                ],
                "uses_model": False,
            },
            {
                "name": "Order & Seller Agent",
                "nodes": ["order_seller_agent"],
                "uses_model": True,
                "data_access": ["orders", "order_items", "sellers"],
            },
            {
                "name": "Payment Agent",
                "nodes": ["payment_agent"],
                "uses_model": True,
                "data_access": ["order_items", "order_payments"],
            },
            {
                "name": "Delivery Agent",
                "nodes": ["delivery_agent"],
                "uses_model": True,
                "data_access": ["orders"],
            },
            {
                "name": "Policy Agent",
                "nodes": ["policy_agent"],
                "uses_model": True,
                "data_access": ["domain_handoffs", POLICY_VERSION],
            },
            {
                "name": "Verifier Agent",
                "nodes": ["verifier_agent"],
                "uses_model": False,
                "data_access": ["source_facts", "policy_oracle", "output_schema"],
            },
        ],
        "execution": {
            "mode": "online",
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "case_concurrency": concurrency,
            "llm_max_concurrency": llm_concurrency,
            "input_cases": len(outputs),
            "completed_cases": len(outputs),
            "failed_cases": 0,
            "issue_counts": dict(sorted(issue_counts.items())),
            "output_dir": "output",
            "trace_path": "logging/trace.jsonl",
            "trace_event_count": len(trace.events),
            "trace_timestamp_policy": "UTC wall clock clamped nondecreasing by sequence",
            "llm_usage": trace.usage,
        },
        "reproducibility": {
            "input_collection_sha256": input_collection_sha256(input_paths),
            "source_sha256": {
                path.name: sha256_file(path) for path in source_paths
            },
            "requirements_file": "requirements.txt",
            "api_key_logged": False,
            "trace_overwrite_mode": True,
        },
    }


async def run_pipeline(concurrency: int, llm_concurrency: int) -> None:
    load_project_environment()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing. Put it in the untracked project .env file."
        )
    if concurrency < 1 or llm_concurrency < 1:
        raise ValueError("Concurrency values must be positive")

    repository = DataRepository()
    if len(repository.cases) != EXPECTED_CASE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_CASE_COUNT} inputs, found {len(repository.cases)}"
        )
    expected_output_names = {f"{case['case_id']}.json" for case in repository.cases}
    extra_output_names = {
        path.name for path in OUTPUT_DIR.glob("*.json")
    } - expected_output_names
    if extra_output_names:
        raise RuntimeError(
            f"Unexpected JSON files already in output/: {sorted(extra_output_names)}"
        )

    started_wall = time.perf_counter()
    started_at = utc_now()
    run_id = (
        "run_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_"
        + uuid.uuid4().hex[:8]
    )
    trace = TraceCollector(run_id)
    await trace.emit(
        "run_started",
        details={
            "model": MODEL_NAME,
            "framework": "LangGraph",
            "policy_version": POLICY_VERSION,
            "input_cases": len(repository.cases),
            "trace_mode": "overwrite_after_success",
        },
    )
    model = StructuredModelClient(
        api_key=api_key, trace=trace, max_concurrency=llm_concurrency
    )
    workflow = MultiAgentGraph(model=model, trace=trace)
    semaphore = asyncio.Semaphore(concurrency)
    outputs: dict[str, dict[str, Any]] = {}

    async def process_case(case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        order_id = case["customer_request"]["claimed_order_id"]
        facts = repository.facts_for_case(case)
        async with semaphore:
            case_started = time.perf_counter()
            await trace.emit(
                "case_started",
                case_id=case_id,
                order_id=order_id,
                details={
                    "input_path": f"input/{case_id}.json",
                    "policy_version": case["policy_version"],
                },
            )
            try:
                output = await workflow.run_case(case, facts)
                final_checks = verify_case_output(output, facts)
                duration_ms = round((time.perf_counter() - case_started) * 1000)
                await trace.emit(
                    "case_completed",
                    case_id=case_id,
                    order_id=order_id,
                    duration_ms=duration_ms,
                    details={
                        "output_path": f"output/{case_id}.json",
                        "assessment": output["assessment"],
                        "financial_resolution": output["financial_resolution"],
                        "verification": final_checks,
                    },
                )
                return output
            except BaseException as exc:
                await trace.emit(
                    "case_failed",
                    case_id=case_id,
                    order_id=order_id,
                    status="error",
                    duration_ms=round((time.perf_counter() - case_started) * 1000),
                    details={
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    },
                )
                raise

    results = await asyncio.gather(
        *(process_case(case) for case in repository.cases), return_exceptions=True
    )
    failures: list[str] = []
    for case, result in zip(repository.cases, results):
        if isinstance(result, BaseException):
            failures.append(f"{case['case_id']}: {type(result).__name__}: {result}")
        else:
            outputs[case["case_id"]] = result
    if failures:
        await trace.emit(
            "run_failed",
            status="error",
            details={"failed_cases": len(failures), "errors": failures},
        )
        raise RuntimeError("Online run failed; successful artifacts were not replaced:\n" + "\n".join(failures))

    if set(outputs) != {case["case_id"] for case in repository.cases}:
        raise RuntimeError("Output case set differs from input case set")
    for case_id in sorted(outputs):
        atomic_write_json(OUTPUT_DIR / f"{case_id}.json", outputs[case_id])

    finished_at = utc_now()
    duration_ms = round((time.perf_counter() - started_wall) * 1000)
    await trace.emit(
        "run_completed",
        duration_ms=duration_ms,
        details={
            "completed_cases": len(outputs),
            "failed_cases": 0,
            "llm_usage": trace.usage,
            "output_files": len(list(OUTPUT_DIR.glob("EC_*.json"))),
        },
    )
    metadata = build_metadata(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        trace=trace,
        outputs=outputs,
        concurrency=concurrency,
        llm_concurrency=llm_concurrency,
    )
    trace.write_jsonl(TRACE_PATH)
    atomic_write_json(METADATA_PATH, metadata)
    print(
        json.dumps(
            {
                "status": "PASS",
                "run_id": run_id,
                "completed_cases": len(outputs),
                "model_calls": trace.usage["model_calls"],
                "total_tokens": trace.usage["total_tokens"],
                "duration_ms": duration_ms,
                "trace": str(TRACE_PATH.relative_to(PROJECT_ROOT)),
                "metadata": str(METADATA_PATH.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all 50 Olist dispute cases through the online multi-agent graph."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Maximum cases running concurrently (default: 5).",
    )
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=8,
        help="Maximum simultaneous OpenAI requests (default: 8).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        asyncio.run(run_pipeline(args.concurrency, args.llm_concurrency))
    except KeyboardInterrupt:
        print("Interrupted; successful artifacts were not replaced.", file=sys.stderr)
        return 130
    except BaseException as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
