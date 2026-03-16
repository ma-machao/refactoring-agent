import json
import os
import re
import time
from typing import Optional

import requests
from dotenv import load_dotenv


load_dotenv()


class LLMClient:
    def __init__(self, model: Optional[str] = None):
        self.api_key = os.getenv("OPENAI_API_KEY")
        #  self.api_key = "asdf"
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://aicoding.2233.ai").rstrip("/")
        self.model = model or os.getenv("OPENAI_MODEL", "claude-opus-4-6")

        if not self.api_key:
            raise ValueError("OPENAI_API_KEY 未设置")

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> str:
        url = f"{self.base_url}/v1/messages"

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }

        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

        start = time.time()
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        latency = round(time.time() - start, 2)
        print(f"[LLM] latency={latency}s status={resp.status_code}")

        if resp.status_code >= 400:
            raise ValueError(f"LLM 请求失败: {resp.status_code} {resp.text}")

        data = resp.json()
        text = self._extract_text(data)
        return self._clean_text(text)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        timeout: int = 120,
    ) -> dict:
        raw = self.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        parsed = self.try_parse_json(raw)
        if parsed is None:
            raise ValueError(f"LLM 输出不是合法 JSON。\n原始输出:\n{raw}")

        return parsed

    def try_parse_json(self, text: str) -> Optional[dict]:
        text = self._extract_json_block(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _extract_text(self, data: dict) -> str:
        content = data.get("content", [])
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(t for t in texts if t)

        return data.get("output_text", "") or data.get("text", "")

    def _clean_text(self, text: str) -> str:
        if not text:
            return text

        text = text.strip()

        if text.startswith("```"):
            text = text.replace("```json", "")
            text = text.replace("```", "")

        return text.strip()

    def _extract_json_block(self, text: str) -> str:
        text = self._clean_text(text)

        # 优先提取最外层 JSON 对象
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0).strip()

        return text.strip()


if __name__ == '__main__':
    llm = LLMClient()
    text = llm.complete(
        system_prompt="你是一个测试助手。",
        user_prompt="请只回复：你好，测试成功",
    )
    print(text)
