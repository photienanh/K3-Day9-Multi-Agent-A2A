# -*- coding: utf-8 -*-
"""Research Agent — retrieves EC_POLICY_V1 + Olist schema notes from local docs
and (when online) a public dataset page, then returns a structured brief for
Policy / LLM agents. Does not invent refund numbers.
"""
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Public page about the same Olist dataset cited in the assignment README.
OLIST_DOC_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"


class ResearchAgent:
    """Gathers policy/schema context before PolicyAgent decides."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self._cache = None

    def research(self) -> dict:
        if self._cache is not None:
            return self._cache
        local = self._read_local_policy()
        web = self._fetch_web_notes()
        brief = {
            "policy_version": "EC_POLICY_V1",
            "priority_issues": [
                "canceled_order_paid",
                "unavailable_order_paid",
                "late_delivery_seller",
                "late_delivery_logistics",
                "valid_split_payment",
                "unsupported_late_claim",
            ],
            "evidence_formats": [
                "order:<order_id>",
                "item:<order_id>:<order_item_id>",
                "payment:<order_id>:<payment_sequential>",
                "seller:<seller_id>",
                "policy:<root_cause_code>",
            ],
            "rules_text": local.get("rules_excerpt", ""),
            "web_source": web.get("url"),
            "web_ok": web.get("ok", False),
            "web_snippet": web.get("snippet", ""),
            "notes": [
                "Compare timestamps as raw CSV strings; no timezone conversion.",
                "payment_value is per payment row, not per installment.",
                "No item rows => empty item_ids/seller_ids and zero item/freight totals.",
                "Seller late iff order_delivered_carrier_date > item.shipping_limit_date.",
                "Money rounded to 2 decimals; payment match tolerance 0.10 BRL.",
            ],
        }
        self._cache = brief
        return brief

    def _read_local_policy(self) -> dict:
        readme = (self.root / "README.md").read_text(encoding="utf-8", errors="ignore")
        # Capture the business-rules table section
        m = re.search(r"## 4\..*?(?=## 5\.)", readme, flags=re.S)
        arch = ""
        ap = self.root / "architecture.md"
        if ap.exists():
            arch = ap.read_text(encoding="utf-8", errors="ignore")[:2000]
        return {
            "rules_excerpt": (m.group(0) if m else readme[:2500])[:3000],
            "architecture_excerpt": arch,
        }

    def _fetch_web_notes(self) -> dict:
        try:
            req = urllib.request.Request(
                OLIST_DOC_URL,
                headers={"User-Agent": "K3-Day9-ResearchAgent/1.0"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read(8000).decode("utf-8", errors="ignore")
            # Strip tags lightly for a short snippet
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return {"ok": True, "url": OLIST_DOC_URL, "snippet": text[:500]}
        except Exception as e:
            return {"ok": False, "url": OLIST_DOC_URL, "snippet": f"fetch_failed:{type(e).__name__}"}

    def to_prompt_block(self, brief: dict = None) -> str:
        brief = brief or self.research()
        return json.dumps({
            "policy_version": brief["policy_version"],
            "priority_issues": brief["priority_issues"],
            "evidence_formats": brief["evidence_formats"],
            "notes": brief["notes"],
            "web_ok": brief["web_ok"],
            "web_source": brief["web_source"],
        }, ensure_ascii=False)
