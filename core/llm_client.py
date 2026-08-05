import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            print("Warning: OPENAI_API_KEY is not set correctly in .env")
        
        self.client = OpenAI(api_key=self.api_key)
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
