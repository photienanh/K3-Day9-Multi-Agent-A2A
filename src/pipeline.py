"""CLI entrypoint for the 50-case online LangGraph run."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .agents import MultiAgentGraph
from .config import (
    EXPECTED_CASE_COUNT,
    METADATA_PATH,
    MODEL_NAME,
    OUTPUT_DIR,
    POLICY_VERSION,
    PROJECT_ROOT,
    TRACE_PATH,
    load_project_environment,
)
from .data_repository import DataRepository
from .llm import StructuredModelClient
from .policy import verify_case_output
from .tracing import TraceCollector, atomic_write_json


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_installed"


def build_metadata() -> dict[str, Any]:
    """Return the compact submission metadata requested by the assignment."""

    return {
        "model": {
            "name": MODEL_NAME,
            "parameter_size": "~8B",
        },
        "framework": {
            "name": "LangGraph",
            "version": package_version("langgraph"),
        },
        "runtime": {
            "python": platform.python_version(),
        },
        "policy": {
            "version": POLICY_VERSION,
        },
        "agents": [
            {"name": "Coordinator Agent", "uses_model": False},
            {"name": "Order & Seller Agent", "uses_model": True},
            {"name": "Payment Agent", "uses_model": True},
            {"name": "Delivery Agent", "uses_model": True},
            {"name": "Policy Agent", "uses_model": True},
            {"name": "Verifier Agent", "uses_model": False},
        ],
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
    metadata = build_metadata()
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
