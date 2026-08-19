# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 server.py 的 tool_dispatch_context_brief；讀目標 repo 的檔案清單與片段，經 providers/outbound.py 檢查後由 providers/http.py 送出；產物寫進 job.contextBrief
# 檔案路徑: dev-triangle-mcp/providers/context_broker.py
# 產生時間: 2026-08-19 15:15 +08:00
# 版本: v1.0
# 功能說明: 第一棒。吞下整個 repo 的結構與使用者需求，請一個便宜的模型整理成結構化情報摘要，重點是列出「這件事會動到哪些檔案」讓下一棒不必自己翻
# 模組定位: L1 情報層 adapter。它「是」摘要的產生者；它「不是」寫程式的那一棒（那是 providers/architect.py），也「不是」唯一輸入——Architect 同時會拿到可回查的原檔路徑清單（S7.2 裁決）
# 主要責任:
#   1. detect(binding) —— 這個角色現在能不能用
#   2. build_repo_digest(repo_path) —— 把 repo 結構壓成可餵給模型的文字
#   3. create_brief(...) —— 送出並解析回應，回傳含 targetBaseUrl/targetModel 的 contextBrief
#   4. impactedFiles 逐條回查，路徑不存在即整筆拒收
# 維護提醒:
#   - 不得跳過 providers/outbound.py 直送。這是本專案第一條自動把 repo 內容往外送的路徑，先開路再補護欄等於中間那段時間的外洩沒有紀錄可查
#   - impactedFiles 回傳不存在的路徑時不得「順手過濾掉」。過濾掉會讓 S4.3 的 context_brief_recall 分母失真，看起來很漂亮但沒有意義
#   - MAX_BRIEF_CHARS 是保護下游推理成本的硬上限，截斷時必須保住 impactedFiles，砍的是次要描述
#   - 回傳一定要帶 targetBaseUrl 與 targetModel（INV-15c）。那是使用者在結果裡看見「東西被送去哪」的唯一機會
# 驗證方式:
#   - python -m pytest -q tests\test_context_broker.py
# ------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from providers import dispatch, outbound
from providers.profiles import RoleBinding


# About 8k tokens. Past this the second leg's context window and bill both start
# to hurt, and the extra prose is rarely what made the difference.
MAX_BRIEF_CHARS = 30000

MAX_DIGEST_FILES = 400
MAX_DIGEST_CHARS = 40000

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    ".dev-triangle",
    ".dev-triangle-test",
    ".dev-triangle-report-test",
    "demo-output",
    "logs",
}

SYSTEM_PROMPT = (
    "You are the context broker for a software task. Read the repository outline and the request, "
    "then reply with STRICT JSON only, no prose and no code fences, using exactly these keys:\n"
    '{"repoSummary": string, "impactedFiles": [repo-relative paths that already exist], '
    '"keyDependencies": [string], "sourceRefs": [repo-relative paths worth reading in full]}\n'
    "Every path in impactedFiles and sourceRefs must be a file that exists in the outline. "
    "Do not invent paths. If you are unsure a file exists, leave it out."
)


class BriefError(Exception):
    pass


def detect(binding: RoleBinding) -> dict[str, Any]:
    return {
        "slot": binding.slot,
        "displayName": binding.label,
        "kind": binding.kind,
        "configured": binding.configured,
        "enabled": binding.enabled,
        "dialect": binding.dialect,
        **dispatch.destination_of(binding),
    }


def iter_repo_files(repo_path: Path, limit: int = MAX_DIGEST_FILES) -> list[Path]:
    found: list[Path] = []
    for path in sorted(repo_path.rglob("*")):
        if len(found) >= limit:
            break
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(repo_path).parts):
            continue
        found.append(path)
    return found


def build_repo_digest(repo_path: Path, limit: int = MAX_DIGEST_FILES) -> str:
    lines: list[str] = [f"# Repository outline: {repo_path.name}", ""]
    for path in iter_repo_files(repo_path, limit):
        rel = path.relative_to(repo_path).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        lines.append(f"- {rel} ({size} bytes)")
    digest = "\n".join(lines)
    if len(digest) > MAX_DIGEST_CHARS:
        digest = digest[:MAX_DIGEST_CHARS] + "\n... outline truncated ..."
    return digest


def parse_brief_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise BriefError(f"Context broker did not return JSON. First 200 chars: {cleaned[:200]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise BriefError(f"Context broker returned malformed JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise BriefError("Context broker returned JSON that is not an object.")
    return parsed


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def verify_paths_exist(repo_path: Path, paths: list[str], field: str) -> None:
    missing = [item for item in paths if not (repo_path / item).exists()]
    if missing:
        # Filtering these out silently would flatter S4.3's recall metric while
        # hiding the exact failure it exists to catch.
        raise BriefError(
            f"Context broker returned {field} that do not exist in {repo_path}: {missing[:10]}. "
            "The brief is rejected rather than trimmed, because a trimmed brief makes the recall "
            "metric look better than the run actually was."
        )


def truncate_brief(brief: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if len(json.dumps(brief, ensure_ascii=False)) <= MAX_BRIEF_CHARS:
        return brief, False
    trimmed = dict(brief)
    summary = trimmed.get("repoSummary", "")
    overflow = len(json.dumps(trimmed, ensure_ascii=False)) - MAX_BRIEF_CHARS
    # Keep impactedFiles whole; the prose is what gets cut.
    trimmed["repoSummary"] = summary[: max(0, len(summary) - overflow - 40)] + "\n... summary truncated ..."
    return trimmed, True


def create_brief(
    binding: RoleBinding,
    repo_path: Path,
    user_request: str,
    multimodal_paths: list[str] | None = None,
) -> dict[str, Any]:
    outbound.require_allowed(repo_path)

    digest = build_repo_digest(repo_path)
    user_payload = "\n\n".join(
        [
            f"## Request\n{user_request}",
            f"## Repository outline\n{digest}",
            # S5 item 3: first version records paths only, it does not upload them.
            f"## Attached file paths (not uploaded)\n{json.dumps(multimodal_paths or [])}",
        ]
    )
    # INV-06: fail-closed before anything leaves the machine.
    safe_payload = outbound.prepare_payload(user_payload)
    safe_system = outbound.prepare_payload(SYSTEM_PROMPT)

    parsed, response = dispatch.send_expecting_json(binding, safe_system, safe_payload, parse_brief_json)

    impacted = string_list(parsed.get("impactedFiles"))
    source_refs = string_list(parsed.get("sourceRefs"))
    if not impacted:
        raise BriefError("Context broker returned no impactedFiles; there is nothing for the next leg to act on.")
    verify_paths_exist(repo_path, impacted, "impactedFiles")
    verify_paths_exist(repo_path, source_refs, "sourceRefs")

    usage = response.get("usage") or {}
    brief = {
        "author": f"contextBroker:{binding.label}",
        "multimodalPaths": list(multimodal_paths or []),
        "repoSummary": str(parsed.get("repoSummary", "")),
        "impactedFiles": impacted,
        "keyDependencies": string_list(parsed.get("keyDependencies")),
        "sourceRefs": source_refs,
        "tokensIn": int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
        "tokensOut": int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
        # INV-15(c)
        "targetBaseUrl": response["targetBaseUrl"],
        "targetModel": response["targetModel"],
    }
    brief, truncated = truncate_brief(brief)
    brief["truncated"] = truncated
    brief["inputChars"] = len(safe_payload)
    brief["briefChars"] = len(json.dumps(brief, ensure_ascii=False))
    brief["compressionRatio"] = round(brief["briefChars"] / max(1, brief["inputChars"]), 4)
    return brief
