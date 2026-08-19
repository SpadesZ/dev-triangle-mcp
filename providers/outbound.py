# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 providers/context_broker.py、providers/architect.py 與 self-heal 的錯誤回送；讀 config/outbound-repos.json；下游只回傳「可以送/不可以送」，本身不發任何請求
# 檔案路徑: dev-triangle-mcp/providers/outbound.py
# 產生時間: 2026-08-19 15:05 +08:00
# 版本: v1.0
# 功能說明: 回答兩個問題——這個 repo 的內容可不可以離開這台機器，以及這段 payload 裡有沒有秘密。兩者任一不通過就拒送，不做「改一改再送」
# 模組定位: L8 護欄層的策略面。它「是」fail-closed 的閘門；它「不是」偵測規則的來源（規則在 providers/redaction.py），也「不是」傳輸層
# 主要責任:
#   1. allowed_repos() / require_allowed(repo) —— 擁有者裁決的 repo 白名單（I4 gate #3）
#   2. prepare_payload(text) —— 遮罩家目錄、掃描秘密，命中即 raise
#   3. OutboundBlocked —— 呼叫端據此回報被擋的原因
# 維護提醒:
#   - 名單檔不存在或為空時必須「全部拒送」，不得視為「全部允許」。這是本檔存在的唯一理由
#   - 不得改成「命中就把秘密塗掉再送」。塗掉之後送出的是一段你沒看過的東西，而 F3 是無徵兆失效，寧可誤報
#   - 例外訊息不得帶命中的原文，見 docs/NOTES.md NOTE-003
# 驗證方式:
#   - python -m pytest -q tests\test_context_broker.py
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from providers.profiles import config_dir
from providers.redaction import redact_payload


ALLOWLIST_FILENAME = "outbound-repos.json"
# Means "the repo this MCP server itself lives in", so the committed allowlist
# does not have to hardcode one machine's drive letter.
SELF_TOKEN = "<self>"

SERVER_REPO_ROOT = Path(__file__).resolve().parent.parent


class OutboundBlocked(Exception):
    pass


def allowlist_path() -> Path:
    return config_dir() / ALLOWLIST_FILENAME


def allowed_repos() -> list[str]:
    path = allowlist_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # An unreadable allowlist is not an empty one in spirit, but it is in
        # effect: nothing is allowed until a human fixes the file.
        return []
    entries = raw.get("allowedRepos")
    if not isinstance(entries, list):
        return []
    return [str(item) for item in entries if isinstance(item, str) and item.strip()]


def resolve_entry(entry: str) -> Path:
    if entry.strip() == SELF_TOKEN:
        return SERVER_REPO_ROOT
    return Path(os.path.expandvars(entry)).expanduser()


def is_allowed(repo_path: Path) -> bool:
    target = repo_path.resolve()
    for entry in allowed_repos():
        try:
            candidate = resolve_entry(entry).resolve()
        except OSError:
            continue
        if candidate == target:
            return True
    return False


def require_allowed(repo_path: Path) -> None:
    if is_allowed(repo_path):
        return
    raise OutboundBlocked(
        f"OUTBOUND_NOT_ALLOWED: {repo_path} is not in {allowlist_path()}. "
        f"Currently allowed: {allowed_repos() or 'nothing'}. Sending a repo's contents to an external "
        "API is an explicit, per-repo decision; there is no default."
    )


def prepare_payload(text: str) -> str:
    """Mask home paths and refuse outright on any secret hit (INV-06)."""
    masked, hits = redact_payload(text)
    if hits:
        patterns = sorted({hit["pattern"] for hit in hits})
        raise OutboundBlocked(
            f"OUTBOUND_BLOCKED: the payload matched {patterns}. Nothing was sent. "
            "This project refuses rather than rewriting: a payload edited to look clean is one "
            "nobody has read."
        )
    return masked


def outbound_status() -> dict[str, Any]:
    return {
        "allowlistPath": str(allowlist_path()),
        "allowedRepos": allowed_repos(),
        "serverRepoRoot": str(SERVER_REPO_ROOT),
    }
