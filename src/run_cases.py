# -*- coding: utf-8 -*-
"""Run all 50 cases with Research + real local LLM + multi-agent handoff.

Requires Ollama running with qwen2.5:7b pulled. Refuses to run without LLM.
"""
import json
import time
from pathlib import Path

from llm import make_llm, MODEL_NAME, PARAMETER_SIZE
from pipeline import Coordinator, DataStore, Trace
from research import ResearchAgent

ROOT = Path(__file__).resolve().parents[1]


def main():
    start = time.time()
    store = DataStore(ROOT)
    trace = Trace()
    research = ResearchAgent(ROOT)
    llm = make_llm()
    print(f"LLM backend: {llm.model_name}, warming up...")
    llm.warm_up()
    print("Research agent: gathering EC_POLICY_V1 + Olist web notes...")
    brief = research.research()
    print(f"  web_ok={brief['web_ok']} source={brief['web_source']}")

    coordinator = Coordinator(store, trace, llm=llm, research=research)

    inputs = sorted((ROOT / "input").glob("EC_*.json"))
    if len(inputs) != 50:
        raise RuntimeError(f"expected 50 inputs, found {len(inputs)}")

    llm_matches = 0
    for f in inputs:
        case = json.loads(f.read_text(encoding="utf-8"))
        result = coordinator.handle_case(case)
        (ROOT / "output" / f.name).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        last_llm = [x for x in trace.lines
                    if x["case_id"] == case["case_id"] and x["from_agent"] == "llm_policy_agent"][-1]
        matched = "match=True" in last_llm["summary"]
        if matched:
            llm_matches += 1
        print(f"{case['case_id']}: {result['assessment']['primary_issue']} "
              f"refund={result['financial_resolution']['recommended_refund_brl']} "
              f"llm={'OK' if matched else 'DIFF'}")

    (ROOT / "logging" / "trace.jsonl").write_text(
        "\n".join(json.dumps(line, ensure_ascii=False) for line in trace.lines) + "\n",
        encoding="utf-8")

    runtime = round(time.time() - start, 2)
    metadata = {
        "model": MODEL_NAME,
        "parameter_size": PARAMETER_SIZE,
        "llm_used_this_run": True,
        "llm_backend": "ollama_local",
        "llm_calls": len(inputs),
        "llm_rule_match_count": llm_matches,
        "research_agent": True,
        "research_web_source": brief.get("web_source"),
        "research_web_ok": brief.get("web_ok"),
        "framework": "custom Python A2A multi-agent (Research + pandas tools + Ollama LLM)",
        "runtime_seconds": runtime,
        "cases": len(inputs),
    }
    (ROOT / "logging" / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (ROOT / "trace.jsonl").write_text(
        (ROOT / "logging" / "trace.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    (ROOT / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print(f"\nDone: {len(inputs)} cases in {runtime}s | "
          f"LLM={MODEL_NAME} match_rule={llm_matches}/{len(inputs)}")


if __name__ == "__main__":
    main()
