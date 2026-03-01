#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from typing import Any


def _extract_text(payload: Any) -> str:
    if isinstance(payload, dict):
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                texts = [item.get("text", "") for item in content if isinstance(item, dict)]
                joined = "\n".join(x for x in texts if x)
                if joined:
                    return joined.strip()
        for key in ("reply", "text", "output_text", "content"):
            value = payload.get(key)
            if isinstance(value, str):
                return value.strip()
    raise ValueError("Unable to extract text from MiniMax response")


class MiniMaxClient:
    def __init__(
        self,
        api_key: str | None = None,
        api_url: str | None = None,
        model: str | None = None,
        timeout: int = 90,
    ) -> None:
        self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
        self.api_url = api_url or os.getenv("MINIMAX_API_URL")
        self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.api_key and self.api_url)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("Missing MiniMax API key")
        if not self.api_url:
            raise RuntimeError("Missing MiniMax API URL")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if extra_payload:
            payload.update(extra_payload)

        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax request failed: {exc}") from exc

        return _extract_text(json.loads(raw))


def main() -> None:
    parser = argparse.ArgumentParser(description="MiniMax chat helper")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system")
    parser.add_argument("--api-key")
    parser.add_argument("--api-url")
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int)
    args = parser.parse_args()

    client = MiniMaxClient(
        api_key=args.api_key,
        api_url=args.api_url,
        model=args.model,
    )
    messages: list[dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})
    print(client.chat(messages, temperature=args.temperature, max_tokens=args.max_tokens))


if __name__ == "__main__":
    main()

