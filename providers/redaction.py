# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 server.py 的 scan_repo_for_publish_safety()（發布前掃描）與後續 W05/W06/W07 的外送路徑、W13 的設定寫入；下游只回傳判斷結果，不自己送出任何東西、不寫檔
# 檔案路徑: dev-triangle-mcp/providers/redaction.py
# 產生時間: 2026-08-19 11:25 +08:00
# 版本: v1.0
# 功能說明: 判斷一段文字裡有沒有疑似金鑰，以及把使用者家目錄的絕對路徑換成 <HOME>。本專案所有「這串東西可不可以離開這台機器」的判斷都走這裡，只有這一份規則
# 模組定位: L8 護欄層的規則來源。它「是」偵測器與遮罩器；它「不是」策略——命中之後要拒送還是只警告由呼叫端決定（本專案的呼叫端一律 fail-closed）。它也「不是」加密或雜湊工具
# 主要責任:
#   1. SENSITIVE_FILE_NAME_PATTERNS / SECRET_CONTENT_PATTERNS —— 從 server.py 原封搬過來的 repo 掃描規則
#   2. redact_payload(text) —— 外送前檢查，回傳 (家目錄已遮罩的文字, hits)
#   3. looks_like_secret_value(value) —— 單一值的判斷，給 apiKeyEnv 與 NL 設定通道用
#   4. mask_home_paths(text) —— 家目錄絕對路徑換成 <HOME>
# 維護提醒:
#   - 不得再寫第二套秘密偵測規則。W13 的 INV-13、W05/W06/W07 的 INV-06 全部共用本檔；分家的那一刻，其中一份就會先鬆掉
#   - SECRET_CONTENT_PATTERNS 的內容不得為了讓 payload 檢查更嚴而修改。它同時餵給 scan_repo_for_publish_safety()，改它就等於改 prepare_jules_repo 的行為（W08 明文禁止）。要加 payload 專用規則請加進 PAYLOAD_ONLY_PATTERNS
#   - hits 不得回傳命中的原文，見 docs/NOTES.md NOTE-003
#   - redact_payload 不是「洗乾淨再送」的工具。它只遮家目錄路徑；命中秘密時呼叫端必須拒送，不得自行改寫後放行
# 驗證方式:
#   - python -m pytest -q tests\test_redaction.py
# ------------------------------------------------------------

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


HOME_PLACEHOLDER = "<HOME>"

# ---------------------------------------------------------------------------
# Repo publish scan rules.
#
# Moved verbatim out of server.py. scan_repo_for_publish_safety() imports these
# and must keep behaving exactly as it did before the move.
# ---------------------------------------------------------------------------

SENSITIVE_FILE_NAME_PATTERNS = [
    re.compile(r"^\.env($|\.)", re.IGNORECASE),
    re.compile(r"^id_rsa($|\.)", re.IGNORECASE),
    re.compile(r"^id_dsa($|\.)", re.IGNORECASE),
    re.compile(r"^id_ed25519($|\.)", re.IGNORECASE),
    re.compile(r".*\.pem$", re.IGNORECASE),
    re.compile(r".*\.p12$", re.IGNORECASE),
    re.compile(r".*\.pfx$", re.IGNORECASE),
]

SECRET_CONTENT_PATTERNS = [
    ("jules_api_key", re.compile(r"\bJULES_API_KEY\s*=\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE)),
    ("openai_api_key", re.compile(r"\bOPENAI_API_KEY\s*=\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE)),
    ("anthropic_api_key", re.compile(r"\bANTHROPIC_API_KEY\s*=\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE)),
    ("github_token", re.compile(r"\b(GITHUB_TOKEN|GH_TOKEN)\s*=\s*['\"]?[^'\"\s]{8,}", re.IGNORECASE)),
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("jules_key_shape", re.compile(r"\bAQ\.[A-Za-z0-9_-]{20,}\b")),
    ("generic_private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
]

# ---------------------------------------------------------------------------
# Payload-only rules.
#
# These catch bare credential shapes that arrive without a NAME= prefix, which
# is what a value pasted into a chat message or echoed by a failing test looks
# like. They are deliberately NOT part of the repo scan: a repo full of example
# strings would produce blocking findings that never mattered before.
# ---------------------------------------------------------------------------

PAYLOAD_ONLY_PATTERNS = [
    ("openai_key_shape", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_key_shape", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("slack_token_shape", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("aws_access_key_shape", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}")),
    ("pem_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


def payload_patterns() -> list[tuple[str, re.Pattern[str]]]:
    return [*SECRET_CONTENT_PATTERNS, *PAYLOAD_ONLY_PATTERNS]


# ---------------------------------------------------------------------------
# Home path masking
# ---------------------------------------------------------------------------


def home_candidates() -> list[str]:
    values: list[str] = []
    for name in ("USERPROFILE", "HOME"):
        value = os.environ.get(name, "").strip()
        if value:
            values.append(value)
    try:
        values.append(str(Path.home()))
    except (RuntimeError, OSError):
        pass
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = value.rstrip("\\/")
        if len(cleaned) < 4:
            # A one- or two-character "home" would mask half the payload.
            continue
        key = cleaned.lower() if os.name == "nt" else cleaned
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return sorted(unique, key=len, reverse=True)


def home_pattern() -> re.Pattern[str] | None:
    alternatives: list[str] = []
    for home in home_candidates():
        segments = [segment for segment in re.split(r"[\\/]+", home) if segment]
        if not segments:
            continue
        # Match either separator: the same path shows up as C:\Users\x in a
        # Windows traceback and C:/Users/x in JSON that went through a codec.
        alternatives.append(r"[\\/]+".join(re.escape(segment) for segment in segments))
    if not alternatives:
        return None
    flags = re.IGNORECASE if os.name == "nt" else 0
    return re.compile("|".join(alternatives), flags)


def mask_home_paths(text: str) -> str:
    pattern = home_pattern()
    if pattern is None:
        return text
    return pattern.sub(HOME_PLACEHOLDER, text)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def looks_like_secret_value(value: str) -> str | None:
    """Return the name of the rule a single value trips, or None.

    Used by the profile loader and the natural-language config tools to tell a
    variable *name* apart from a pasted credential.
    """
    candidate = (value or "").strip()
    if not candidate:
        return None
    for name, pattern in payload_patterns():
        if pattern.search(candidate):
            return name
    # Shape heuristic from SAI A4.6 rule 1: long, and containing characters that
    # an environment variable name cannot contain.
    if len(candidate) > 20 and re.search(r"[-.]", candidate) and not re.fullmatch(r"[A-Za-z0-9_]+", candidate):
        return "high_entropy_shape"
    return None


def scan_payload(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for name, pattern in payload_patterns():
        matches = list(pattern.finditer(text or ""))
        if not matches:
            continue
        # NOTE(NOTE-003): report where and how many, never what. These hits are
        # written to the ledger and echoed back to the caller.
        hits.append(
            {
                "pattern": name,
                "count": len(matches),
                "firstOffset": matches[0].start(),
                "matchedChars": sum(match.end() - match.start() for match in matches),
            }
        )
    return hits


def redact_payload(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Mask home paths and report secret hits.

    The returned text is NOT a sanitized version safe to send when hits is
    non-empty. Callers are fail-closed: any hit means refuse, per INV-06.
    """
    masked = mask_home_paths(text or "")
    return masked, scan_payload(masked)
