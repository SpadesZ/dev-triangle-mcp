# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 server.py 的 tool_dispatch_architect；吃 job.contextBrief 與可回查的原檔內容，經 providers/outbound.py 檢查後由 providers/http.py 送出；產物是 patch 文字，落地與套用由 server.py 負責
# 檔案路徑: dev-triangle-mcp/providers/architect.py
# 產生時間: 2026-08-19 16:00 +08:00
# 版本: v1.0
# 功能說明: 第二棒。吃第一棒整理好的情報摘要，產出一份 unified diff 與一份測試計畫。它只產 patch，不碰使用者的檔案
# 模組定位: L2 實作層 adapter。它「是」patch 的產生者；它「不是」patch 的套用者（那是 server.py 的 tool_apply_patch，L3 落地層），這個分界就是回退點的來源
# 主要責任:
#   1. create_implementation(...) —— 送出並解析，回傳 {patch, testPlan, rationale, targetBaseUrl, targetModel}
#   2. shadow_implementation(...) —— S7.2 的對照組：同一題不經 brief 再跑一次
#   3. 送出前一律過 providers/outbound.py
# 維護提醒:
#   - 不得讓本模組直接寫使用者的檔案。硬約束來自 A1.3：只有「產 patch」與「套 patch」分開，才會有一個可以 git reset 回去的點
#   - brief 不是唯一輸入。sourceRefs 指到的原檔要一起帶上，否則壓縮失真(F2)沒有任何補救管道（S7.2 裁決）
#   - shadow 的兩份結果都要保留，首版不做自動比較。太早自動比較會讓人以為對照已經有結論
#   - 回傳一定要帶 targetBaseUrl 與 targetModel（INV-15c）
# 驗證方式:
#   - python -m pytest -q tests\test_apply_patch.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from providers import http, outbound
from providers.profiles import RoleBinding


MAX_SOURCE_CHARS = 60000

SYSTEM_PROMPT = (
    "You are the implementing engineer. You are given a context brief and the full text of the files "
    "it points at. Reply with STRICT JSON only, no prose and no code fences, using exactly these keys:\n"
    '{"rationale": string, "testPlan": [string], "patch": "a unified diff applicable with git apply"}\n'
    "The patch must use repo-relative paths in the a/ and b/ form. Do not include commentary inside "
    "the patch. If you cannot produce a safe change, return an empty patch string and explain why in "
    "rationale."
)


class ImplementationError(Exception):
    pass


def gather_sources(repo_path: Path, paths: list[str], budget: int = MAX_SOURCE_CHARS) -> str:
    chunks: list[str] = []
    used = 0
    for rel in paths:
        target = repo_path / rel
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        remaining = budget - used
        if remaining <= 0:
            break
        if len(text) > remaining:
            text = text[:remaining] + "\n... file truncated ...\n"
        used += len(text)
        chunks.append(f"### {rel}\n```\n{text}\n```")
    return "\n\n".join(chunks)


def parse_implementation_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ImplementationError(f"Architect did not return JSON. First 200 chars: {cleaned[:200]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ImplementationError(f"Architect returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ImplementationError("Architect returned JSON that is not an object.")
    return parsed


def build_user_payload(user_request: str, brief: dict[str, Any] | None, sources: str) -> str:
    parts = [f"## Request\n{user_request}"]
    if brief is None:
        # S7.2 shadow arm: same question, no brief, so the comparison means
        # something later.
        parts.append("## Context brief\n(none - shadow run, working from the sources directly)")
    else:
        parts.append(
            "## Context brief\n"
            + json.dumps(
                {
                    "repoSummary": brief.get("repoSummary", ""),
                    "impactedFiles": brief.get("impactedFiles", []),
                    "keyDependencies": brief.get("keyDependencies", []),
                    "sourceRefs": brief.get("sourceRefs", []),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    parts.append(f"## Source files\n{sources}")
    return "\n\n".join(parts)


def create_implementation(
    binding: RoleBinding,
    repo_path: Path,
    user_request: str,
    brief: dict[str, Any] | None,
    source_paths: list[str],
) -> dict[str, Any]:
    outbound.require_allowed(repo_path)

    sources = gather_sources(repo_path, source_paths)
    payload = build_user_payload(user_request, brief, sources)
    safe_payload = outbound.prepare_payload(payload)
    safe_system = outbound.prepare_payload(SYSTEM_PROMPT)

    response = http.chat(binding, safe_system, safe_payload)
    parsed = parse_implementation_json(response["text"])

    patch = parsed.get("patch")
    if not isinstance(patch, str):
        raise ImplementationError("Architect returned no patch field.")
    test_plan = parsed.get("testPlan")
    if not isinstance(test_plan, list):
        test_plan = []
    usage = response.get("usage") or {}

    return {
        "author": f"architect:{binding.label}",
        "patch": patch,
        "testPlan": [str(item) for item in test_plan],
        "rationale": str(parsed.get("rationale", "")),
        "shadow": brief is None,
        "tokensIn": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        "tokensOut": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        # INV-15(c)
        "targetBaseUrl": response["targetBaseUrl"],
        "targetModel": response["targetModel"],
    }
