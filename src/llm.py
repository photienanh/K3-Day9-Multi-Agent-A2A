# -*- coding: utf-8 -*-
"""Local LLM agent via Ollama (required for a real submission run).

Model declaration (assignment rule: model name lives in source code, not .env):
    OLLAMA_MODEL = "qwen2.5:7b"   # Qwen2.5 7B params (<= 10B), local Ollama

Role: given tool-derived facts + research brief, propose a primary_issue.
Numbers/timestamps are NEVER computed by the LLM.
"""
import json
import time
import urllib.request

OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = OLLAMA_MODEL
PARAMETER_SIZE = "7B"

VALID_ISSUES = (
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
)


def _post_json(url, body, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def make_llm():
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            models = {m["name"] for m in json.load(resp).get("models", [])}
        if any(name.startswith(OLLAMA_MODEL) for name in models):
            return OllamaPolicyAgent()
    except Exception as e:
        raise RuntimeError(
            f"Ollama not reachable at {OLLAMA_URL}. Start Ollama and "
            f"`ollama pull {OLLAMA_MODEL}` before running. Detail: {e}"
        ) from e
    raise RuntimeError(
        f"Model {OLLAMA_MODEL} not found. Run: ollama pull {OLLAMA_MODEL}"
    )


class OllamaPolicyAgent:
    model_name = OLLAMA_MODEL

    def warm_up(self):
        _post_json(f"{OLLAMA_URL}/api/generate", {
            "model": OLLAMA_MODEL,
            "prompt": "Reply with OK",
            "stream": False,
            "options": {"temperature": 0, "num_predict": 2},
            "keep_alive": "60m",
        }, timeout=600)

    def propose_issue(self, order_f, pay_f, del_f, research_brief: str = "") -> dict:
        facts = {
            "order_status": order_f.get("order_status"),
            "late": bool(del_f["late"]),
            "any_seller_late_vs_shipping_limit": bool(order_f.get("sellers_late")),
            "n_payments": int(pay_f["n_payments"]),
            "payment_matches_item_plus_freight": bool(pay_f["matches_order_total"]),
            "payment_total_gt_zero": bool(pay_f["payment_total"] > 0),
        }
        prompt = (
            "You classify e-commerce disputes using EC_POLICY_V1.\n"
            f"Research brief: {research_brief}\n\n"
            "Priority rules:\n"
            "1. canceled_order_paid — status=canceled AND payment_total_gt_zero\n"
            "2. unavailable_order_paid — status=unavailable AND payment_total_gt_zero\n"
            "3. late_delivery_seller — late=true AND any_seller_late_vs_shipping_limit=true\n"
            "4. late_delivery_logistics — late=true AND any_seller_late_vs_shipping_limit=false\n"
            "5. valid_split_payment — n_payments>=2 AND payment_matches_item_plus_freight=true\n"
            "6. unsupported_late_claim — otherwise\n\n"
            f"Facts: {json.dumps(facts)}\n\n"
            "Reply with ONLY one label from the six above. No explanation."
        )
        t0 = time.time()
        resp = _post_json(f"{OLLAMA_URL}/api/generate", {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 16},
            "keep_alive": "60m",
        }, timeout=600)
        raw = (resp.get("response") or "").strip()
        elapsed_ms = int((time.time() - t0) * 1000)
        return {"issue": self._parse_issue(raw), "raw": raw, "elapsed_ms": elapsed_ms, "facts": facts}

    @staticmethod
    def _parse_issue(raw: str):
        text = raw.strip().lower().replace("`", "").replace('"', "").replace("'", "")
        for label in VALID_ISSUES:
            if text == label or text.startswith(label):
                return label
        for label in VALID_ISSUES:
            if label in text:
                return label
        return None
