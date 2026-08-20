# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；掃描整個 repo 的 *.py 與 *.ps1 以及 docs/NOTES.md；只讀不寫，不啟動子行程
# 檔案路徑: dev-triangle-mcp/tests/test_repo_integrity.py
# 產生時間: 2026-08-19 17:10 +08:00
# 版本: v1.0
# 功能說明: 把「每個原始檔都要有十欄檔頭」「檔頭的驗證方式要指到真的存在的東西」「程式裡的 NOTE 編號要找得到同號條目」這三條規範從人的記性搬進 CI
# 模組定位: 規範的執行者。它「是」docs/CODE_HEADER_SPEC.md 的機械檢查；它「不是」對程式行為的測試，也「不是」風格檢查（縮排、命名之類的一律不管）
# 主要責任:
#   1. test_every_source_file_has_the_ten_field_header —— 欄名齊全
#   2. test_header_verification_targets_exist —— 驗證方式指到的檔案必須存在
#   3. test_every_note_reference_resolves —— NOTE(NOTE-NNN) 必須在 docs/NOTES.md 找得到同號條目
#   4. test_provider_lock_hits_is_zero / test_silent_default_count_is_zero —— S4.8 與 S4.9 兩把量尺
#   5. test_gemini_broker_policy_denies_every_tool —— Broker 的 CLI policy 必須維持全工具拒絕
# 維護提醒:
#   - 新增檔案時要嘛補檔頭，要嘛把它加進 EXEMPT_FILES 並在此寫明理由。不得為了讓測試過就放寬欄名檢查
#   - S4.8 的例外判準只認「同一行提到拒絕清單」，見 docs/NOTES.md NOTE-001。不得改成整個檔案排除——整檔排除就是把量尺關掉
#   - 這支測試會紅通常代表文件真的過期了，不是測試太嚴
# 驗證方式:
#   - python -m pytest -q tests\test_repo_integrity.py
# ------------------------------------------------------------

from __future__ import annotations

import re
from pathlib import Path

import pytest


REQUIRED_FIELDS = (
    "上下游:",
    "檔案路徑:",
    "產生時間:",
    "版本:",
    "功能說明:",
    "模組定位:",
    "主要責任:",
    "維護提醒:",
    "驗證方式:",
)
CONTRACT_MARKER = "source maintenance contract"

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".dev-triangle",
    ".dev-triangle-test",
    ".dev-triangle-report-test",
    "demo-output",
    "logs",
    ".venv",
    "venv",
    "node_modules",
}

# Files that predate the rule and are exempt only with a stated reason.
EXEMPT_FILES: dict[str, str] = {}

NOTE_REFERENCE_RE = re.compile(r"NOTE\(NOTE-(\d{3})\)")
NOTE_ENTRY_RE = re.compile(r"^##\s+NOTE-(\d{3})\s", re.MULTILINE)

# S4.8: hardcoded model version numbers in architecture-layer files.
PROVIDER_LOCK_RE = re.compile(r"(gemini|claude|gpt|codex)[- ]?[0-9]", re.IGNORECASE)
# NOTE-001's mechanical exception: the line is talking about the deny list.
PROVIDER_LOCK_EXEMPT_RE = re.compile(
    r"ANTIGRAVITY_LEGACY_UNSAFE_MODELS|ANTIGRAVITY_AGY_MODEL|legacy unsafe"
)
# S4.9: a fallback that silently decides which model or endpoint runs.
# NOTE(NOTE-008): scoped to assignments and returns, not every mention.
SILENT_DEFAULT_PATTERNS = (
    re.compile(r"\b(model|base_url|baseUrl|provider|endpoint)\w*\s*=\s*[^=].*\bor\b\s*[\"']", re.IGNORECASE),
    re.compile(r"\breturn\b.*\b(model|base_url|baseUrl|provider|endpoint)\b.*\bor\b\s*[\"']", re.IGNORECASE),
)


def is_silent_default(line: str) -> bool:
    return any(pattern.search(line) for pattern in SILENT_DEFAULT_PATTERNS)


def repo_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        found.append(path)
    return found


def source_files(root: Path) -> list[Path]:
    return repo_files(root, (".py", ".ps1"))


def header_block(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            lines.append(stripped)
            continue
        if stripped.startswith("---") or not stripped:
            if lines:
                continue
            continue
        if lines:
            break
    return "\n".join(lines)


def test_every_source_file_has_the_ten_field_header(repo_root: Path) -> None:
    missing: list[str] = []
    for path in source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        if rel in EXEMPT_FILES:
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        if CONTRACT_MARKER not in head:
            missing.append(f"{rel}: no contract header")
            continue
        absent = [field for field in REQUIRED_FIELDS if field not in head]
        if absent:
            missing.append(f"{rel}: missing fields {absent}")
    assert missing == [], "\n".join(missing)


def test_header_declares_its_own_path(repo_root: Path) -> None:
    wrong: list[str] = []
    for path in source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        if rel in EXEMPT_FILES:
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        match = re.search(r"檔案路徑:\s*(\S+)", head)
        if match is None:
            wrong.append(f"{rel}: no 檔案路徑")
            continue
        declared = match.group(1).replace("\\", "/")
        if not declared.endswith(rel):
            wrong.append(f"{rel}: header says {declared}")
    assert wrong == [], "\n".join(wrong)


def test_header_verification_targets_exist(repo_root: Path) -> None:
    # The one field in the header that can be executed, and therefore the one
    # that can be wrong in a way anybody notices.
    broken: list[str] = []
    path_re = re.compile(r"((?:tests|scripts|providers|docs|config)[\\/][\w./\\-]+\.(?:py|ps1|md|json))")
    for path in source_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        section = head.split("驗證方式:", 1)
        if len(section) < 2:
            continue
        block = section[1].split("---", 1)[0]
        for candidate in path_re.findall(block):
            cleaned = candidate.replace("\\", "/").split("::", 1)[0]
            if not (repo_root / cleaned).exists():
                broken.append(f"{rel}: 驗證方式 points at missing {cleaned}")
    assert broken == [], "\n".join(broken)


def test_every_note_reference_resolves(repo_root: Path) -> None:
    notes_path = repo_root / "docs" / "NOTES.md"
    assert notes_path.exists(), "docs/NOTES.md is where the reasons live"
    entries = set(NOTE_ENTRY_RE.findall(notes_path.read_text(encoding="utf-8")))

    dangling: list[str] = []
    for path in source_files(repo_root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number in NOTE_REFERENCE_RE.findall(text):
            if number not in entries:
                dangling.append(f"{path.relative_to(repo_root).as_posix()}: NOTE-{number} has no entry")
    assert dangling == [], "\n".join(dangling)


def test_every_note_entry_has_its_required_fields(repo_root: Path) -> None:
    # A one-line summary does not count: following it has to actually answer why.
    text = (repo_root / "docs" / "NOTES.md").read_text(encoding="utf-8")
    sections = re.split(r"^##\s+NOTE-(\d{3})\s", text, flags=re.MULTILINE)
    incomplete: list[str] = []
    for index in range(1, len(sections), 2):
        number = sections[index]
        body = sections[index + 1]
        for field in ("決策日期", "適用範圍", "決策", "原因", "驗證"):
            if f"**{field}**" not in body:
                incomplete.append(f"NOTE-{number}: missing {field}")
    assert incomplete == [], "\n".join(incomplete)


def test_provider_lock_hits_is_zero(repo_root: Path) -> None:
    # S4.8. docs/SAI.md is excluded by the spec itself: it must quote the
    # owner's words verbatim, so scanning it would make the metric permanently
    # red, which is as useless as one that is permanently green.
    hits: list[str] = []
    for path in repo_files(repo_root, (".py", ".ps1", ".md", ".json")):
        rel = path.relative_to(repo_root).as_posix()
        if rel == "docs/SAI.md":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if PROVIDER_LOCK_RE.search(line) and not PROVIDER_LOCK_EXEMPT_RE.search(line):
                hits.append(f"{rel}:{number}: {line.strip()[:110]}")
    assert hits == [], "hardcoded model version numbers (see NOTE-001):\n" + "\n".join(hits)


def test_silent_default_count_is_zero(repo_root: Path) -> None:
    # S4.9. C9 bans hardcoding a model; C10 says the user picks one. The gap
    # between them is a fallback expression that decides without either.
    hits: list[str] = []
    for path in repo_files(repo_root, (".py",)):
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith("tests/"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if is_silent_default(stripped):
                hits.append(f"{rel}:{number}: {stripped[:110]}")
    assert hits == [], "silent model/endpoint defaults (INV-12):\n" + "\n".join(hits)


def test_gemini_broker_policy_denies_every_tool(repo_root: Path) -> None:
    text = (repo_root / "config" / "gemini-broker-deny-all.toml").read_text(encoding="utf-8")

    assert 'toolName = "*"' in text
    assert 'decision = "deny"' in text
    assert "interactive = false" in text


def test_silent_default_detector_actually_detects() -> None:
    # NOTE(NOTE-008): the S4.9 scan is narrower than the SAI's literal grep, so
    # it has to prove it still catches the thing the metric is named after.
    assert is_silent_default('    model = cfg.get("model") or "some-model"')
    assert is_silent_default('    binding.base_url = base or "https://api.example.invalid"')
    assert is_silent_default('    return cfg.get("model") or "some-model"')
    # And that the two shapes it deliberately ignores are not resolution sites.
    assert not is_silent_default('        "id": short_id(provider or "job"),')
    assert not is_silent_default("""    f"sends to {changes['baseUrl'] or '(adapter default)'}\"""")
