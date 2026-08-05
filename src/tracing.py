"""In-memory, concurrency-safe audit trace with atomic persistence."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRACE_SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=False, default=_json_default
    )
    _atomic_write_text(path, payload + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


class TraceCollector:
    """Collect ordered events and aggregate real model token usage."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._last_timestamp_ms: int | None = None
        self._usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "model_calls": 0,
        }

    async def emit(
        self,
        event: str,
        *,
        case_id: str | None = None,
        order_id: str | None = None,
        agent: str | None = None,
        node: str | None = None,
        status: str = "ok",
        duration_ms: int | None = None,
        handoff: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        async with self._lock:
            self._sequence += 1
            # Wall clocks can move backwards briefly under NTP/virtualization.
            # Clamp only the audit timestamp; measured durations use perf_counter.
            timestamp_ms = time.time_ns() // 1_000_000
            if self._last_timestamp_ms is not None:
                timestamp_ms = max(timestamp_ms, self._last_timestamp_ms)
            self._last_timestamp_ms = timestamp_ms
            timestamp = datetime.fromtimestamp(
                timestamp_ms / 1000, tz=timezone.utc
            ).isoformat(timespec="milliseconds")
            row: dict[str, Any] = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "run_id": self.run_id,
                "sequence": self._sequence,
                "timestamp": timestamp,
                "event": event,
                "status": status,
            }
            if case_id is not None:
                row["case_id"] = case_id
            if order_id is not None:
                row["order_id"] = order_id
            if agent is not None:
                row["agent"] = agent
            if node is not None:
                row["node"] = node
            if duration_ms is not None:
                row["duration_ms"] = duration_ms
            if handoff is not None:
                row["handoff"] = handoff
            if details is not None:
                row["details"] = details
            self.events.append(row)

    async def record_usage(self, usage: dict[str, Any]) -> None:
        async with self._lock:
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            total_tokens = int(
                usage.get("total_tokens") or input_tokens + output_tokens
            )
            self._usage["input_tokens"] += input_tokens
            self._usage["output_tokens"] += output_tokens
            self._usage["total_tokens"] += total_tokens
            self._usage["model_calls"] += 1

    @property
    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    def write_jsonl(self, path: Path) -> None:
        text = "".join(
            json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
                default=_json_default,
            )
            + "\n"
            for event in self.events
        )
        _atomic_write_text(path, text)
