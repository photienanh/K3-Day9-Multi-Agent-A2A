import os
import json
import time
from typing import Type

from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            raise RuntimeError("OPENAI_API_KEY is not configured in .env")
        
        self.client = OpenAI(api_key=self.api_key, timeout=60.0, max_retries=2)
        self.model = "gpt-4o-mini"

    def chat(self, system_prompt: str, user_prompt: str, response_format=None) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
        }
        
        if response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def get_json(self, system_prompt: str, user_prompt: str) -> dict:
        result_text = self.chat(system_prompt, user_prompt, response_format="json_object")
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            print("Error decoding JSON from LLM")
            return {}

    def parse_structured(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        payload: dict,
        response_model: Type[BaseModel],
        max_output_tokens: int = 1200,
    ) -> tuple[dict, dict]:
        """Call gpt-4o-mini and return a schema-validated object plus trace metadata."""
        started = time.perf_counter()
        response = self.client.responses.parse(
            model=self.model,
            instructions=system_prompt,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            text_format=response_model,
            temperature=0.0,
            max_output_tokens=max_output_tokens,
            store=False,
            metadata={"agent": agent_name},
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError(
                f"{agent_name} received no parsed output from {self.model}; "
                f"response_id={response.id}"
            )

        usage = getattr(response, "usage", None)
        llm_trace = {
            "provider": "openai",
            "model": self.model,
            "response_id": response.id,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return parsed.model_dump(), llm_trace
