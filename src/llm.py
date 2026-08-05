"""Shared gpt-4o-mini Structured Output client for LangGraph agents."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .config import MODEL_NAME, MODEL_TEMPERATURE
from .tracing import TraceCollector


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class StructuredModelClient:
    """Runs schema-constrained model calls and records provider metadata."""

    def __init__(
        self,
        api_key: str,
        trace: TraceCollector,
        max_concurrency: int = 8,
    ) -> None:
        self.trace = trace
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._base_model = ChatOpenAI(
            model=MODEL_NAME,
            api_key=api_key,
            temperature=MODEL_TEMPERATURE,
            timeout=60,
            max_retries=3,
        )
        self._structured_models: dict[type[BaseModel], Any] = {}

    def _model_for(self, schema: type[SchemaT]) -> Any:
        if schema not in self._structured_models:
            self._structured_models[schema] = self._base_model.with_structured_output(
                schema,
                method="json_schema",
                strict=True,
                include_raw=True,
            )
        return self._structured_models[schema]

    async def parse(
        self,
        *,
        agent: str,
        node: str,
        case_id: str,
        order_id: str,
        instructions: str,
        payload: dict[str, Any],
        schema: type[SchemaT],
    ) -> dict[str, Any]:
        payload_text = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        request_hash = hashlib.sha256(
            (instructions + "\n" + payload_text).encode("utf-8")
        ).hexdigest()
        await self.trace.emit(
            "llm_request",
            case_id=case_id,
            order_id=order_id,
            agent=agent,
            node=node,
            details={
                "provider": "openai",
                "model": MODEL_NAME,
                "temperature": MODEL_TEMPERATURE,
                "response_format": "json_schema_strict",
                "schema": schema.__name__,
                "request_sha256": request_hash,
                "input": payload,
            },
        )
        started = time.perf_counter()
        try:
            async with self._semaphore:
                response = await self._model_for(schema).ainvoke(
                    [
                        SystemMessage(content=instructions),
                        HumanMessage(content=payload_text),
                    ]
                )
            duration_ms = round((time.perf_counter() - started) * 1000)
            parsing_error = response.get("parsing_error")
            parsed = response.get("parsed")
            raw = response.get("raw")
            if parsing_error is not None or parsed is None:
                raise RuntimeError(
                    f"Structured output parse failed: {parsing_error or 'empty output'}"
                )
            parsed_json = parsed.model_dump(mode="json")
            usage = dict(getattr(raw, "usage_metadata", None) or {})
            response_metadata = dict(getattr(raw, "response_metadata", None) or {})
            await self.trace.record_usage(usage)
            await self.trace.emit(
                "llm_response",
                case_id=case_id,
                order_id=order_id,
                agent=agent,
                node=node,
                duration_ms=duration_ms,
                details={
                    "provider": "openai",
                    "requested_model": MODEL_NAME,
                    "response_model": response_metadata.get(
                        "model_name", MODEL_NAME
                    ),
                    "response_id": getattr(raw, "id", None),
                    "finish_reason": response_metadata.get("finish_reason"),
                    "system_fingerprint": response_metadata.get(
                        "system_fingerprint"
                    ),
                    "usage": usage,
                    "output": parsed_json,
                },
            )
            return parsed_json
        except BaseException as exc:
            duration_ms = round((time.perf_counter() - started) * 1000)
            await self.trace.emit(
                "llm_error",
                case_id=case_id,
                order_id=order_id,
                agent=agent,
                node=node,
                status="error",
                duration_ms=duration_ms,
                details={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise
