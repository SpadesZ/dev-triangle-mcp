# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 providers/context_broker.py 與 providers/architect.py；讀 RoleBinding 決定端點與方言，讀環境變數取金鑰；下游是外部 HTTP API。所有送出去的東西必須已經先過 providers/redaction.py
# 檔案路徑: dev-triangle-mcp/providers/http.py
# 產生時間: 2026-08-19 14:55 +08:00
# 版本: v1.0
# 功能說明: 把「一段對話」用各家 API 各自的形狀包成 HTTP 請求送出去，再把回來的東西拆成純文字。四種方言(openai/anthropic/gemini/ollama)的差別只在這裡處理，adapter 不必知道
# 模組定位: 通用傳輸層。它「是」方言轉換與金鑰讀取；它「不是」遮罩層（呼叫端必須先過 W08）、「不是」重試或速率控制層、也「不是」Jules 專用的 http_json（那支硬寫 x-goog-api-key，只給 Jules 用）
# 主要責任:
#   1. chat(binding, messages, ...) —— 送一輪對話，回純文字
#   2. list_models_for(binding) —— 供 INV-14 比對模型 ID 用；不支援就回 None
#   3. default_base_url(dialect) —— baseUrl 留空時的內建端點
# 維護提醒:
#   - 不得在此檔加任何預設模型。binding.model 為空時直接報錯，那代表上游的 resolve_role 漏了檢查（INV-12）
#   - 不得在此檔做遮罩。遮罩要在呼叫端做，因為 fail-closed 的決定權屬於呼叫端；在這裡遮會讓「被擋下」變成「悄悄送出被改過的內容」
#   - 不得把 api key 值寫進任何回傳值、例外訊息或 log。錯誤訊息只帶狀態碼與端點
#   - 新增方言時必須同時補 chat() 與 list_models_for() 兩處，缺一會讓 INV-14 在那個方言上永遠回 None
# 驗證方式:
#   - python -m pytest -q tests\test_context_broker.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

from providers import models
from providers.profiles import RoleBinding


DEFAULT_TIMEOUT_SEC = 180

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://localhost:11434",
}

ANTHROPIC_VERSION = "2023-06-01"


class TransportError(Exception):
    pass


def default_base_url(dialect: str) -> str:
    return DEFAULT_BASE_URLS.get(dialect, "")


def resolve_base_url(binding: RoleBinding) -> str:
    base = (binding.base_url or default_base_url(binding.dialect)).rstrip("/")
    if not base:
        raise TransportError(
            f"Role {binding.slot!r} has no baseUrl and dialect {binding.dialect!r} has no built-in "
            "endpoint. Set one of them."
        )
    return base


def api_key(binding: RoleBinding) -> str:
    if not binding.api_key_env:
        raise TransportError(f"Role {binding.slot!r} has no apiKeyEnv.")
    value = os.environ.get(binding.api_key_env, "").strip()
    if not value:
        raise TransportError(
            f"Environment variable {binding.api_key_env} is empty, so role {binding.slot!r} has no "
            "credential. This project never stores key values."
        )
    return value


def _request(url: str, method: str, headers: dict[str, str], body: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        # Deliberately no headers and no request body in the message: both carry
        # the credential.
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TransportError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except error.URLError as exc:
        raise TransportError(f"Could not reach {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise TransportError(f"{url} did not return JSON: {exc}") from exc


def chat(binding: RoleBinding, system: str, user: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """Send one exchange and return {"text", "targetBaseUrl", "targetModel", "raw"}."""
    if not binding.model:
        raise TransportError(
            f"Role {binding.slot!r} has no model. resolve_role should have refused before reaching "
            "the transport layer."
        )
    base = resolve_base_url(binding)
    dialect = binding.dialect or "openai"
    key = api_key(binding)

    if dialect == "anthropic":
        url = f"{base}/messages"
        headers = {
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        body: dict[str, Any] = {
            "model": binding.model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        raw = _request(url, "POST", headers, body, timeout)
        text = "".join(part.get("text", "") for part in raw.get("content", []) if isinstance(part, dict))
    elif dialect == "gemini":
        url = f"{base}/models/{binding.model}:generateContent"
        headers = {"content-type": "application/json", "x-goog-api-key": key}
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
        }
        raw = _request(url, "POST", headers, body, timeout)
        candidates = raw.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts", []) if candidates else [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
    elif dialect == "ollama":
        url = f"{base}/api/chat"
        headers = {"content-type": "application/json"}
        body = {
            "model": binding.model,
            "stream": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        raw = _request(url, "POST", headers, body, timeout)
        text = (raw.get("message") or {}).get("content", "")
    else:
        url = f"{base}/chat/completions"
        headers = {"content-type": "application/json", "authorization": f"Bearer {key}"}
        body = {
            "model": binding.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        raw = _request(url, "POST", headers, body, timeout)
        choices = raw.get("choices") or []
        text = (choices[0].get("message", {}).get("content", "") if choices else "")

    usage = raw.get("usage") or raw.get("usageMetadata") or {}
    return {
        # INV-15(c): the caller has to be able to show where this went.
        "targetBaseUrl": base,
        "targetModel": binding.model,
        "text": text,
        "usage": usage,
    }


def list_models_for(binding: RoleBinding) -> list[str] | None:
    """Return the provider's model ids, or None when it cannot be asked.

    None means unverifiable, which INV-14 records as verified: false. It never
    means "empty", and it must never be turned into a refusal.
    """
    dialect = binding.dialect or ""
    try:
        base = resolve_base_url(binding)
        key = api_key(binding)
    except TransportError:
        return None

    try:
        if dialect == "gemini":
            raw = _request(f"{base}/models", "GET", {"x-goog-api-key": key}, None, 60)
            return [str(item.get("name", "")).split("/")[-1] for item in raw.get("models", [])]
        if dialect == "ollama":
            raw = _request(f"{base}/api/tags", "GET", {}, None, 60)
            return [str(item.get("name", "")) for item in raw.get("models", [])]
        if dialect in {"openai", "anthropic"}:
            headers = (
                {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
                if dialect == "anthropic"
                else {"authorization": f"Bearer {key}"}
            )
            raw = _request(f"{base}/models", "GET", headers, None, 60)
            return [str(item.get("id", "")) for item in raw.get("data", [])]
    except TransportError:
        return None
    return None


for _dialect in DEFAULT_BASE_URLS:
    models.register_lister(_dialect, list_models_for)
