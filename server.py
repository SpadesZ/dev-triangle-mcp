"""Dev Triangle MCP main server.

This process is the full control-plane MCP server intended for the
orchestrator agent, currently Codex by default. It exposes tools for:

- Jules cloud coding sessions.
- Local project publishing guards that prepare GitHub repos for Jules.
- Antigravity local validation handoffs.
- The local job ledger used to connect task creation, execution, and results.

Human orientation:
  Codex should see this full server because it owns task routing and review.
  Worker/verifier agents should not see this server by default. They should
  receive a narrow prompt plus the report-only server in
  antigravity_report_server.py.

Safety shape:
  This file intentionally does not expose a generic shell execution tool.
  Antigravity execution is restricted to explicit CLI handoff commands, and
  Jules access is restricted to the Jules REST API adapter.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request


SERVER_NAME = "dev-triangle-mcp"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2025-06-18"

# Runtime state is deliberately separate from source code. For local installs
# this normally points at %USERPROFILE%\.dev-triangle; tests override it with a
# temporary folder so smoke tests cannot mutate the user's real ledger.
ROOT = Path(__file__).resolve().parent
DEV_TRIANGLE_HOME = Path(
    os.environ.get("DEV_TRIANGLE_HOME", str(ROOT / ".dev-triangle"))
).expanduser()
LEDGER_PATH = DEV_TRIANGLE_HOME / "jobs.json"
HANDOFF_DIR = Path(
    os.environ.get("ANTIGRAVITY_HANDOFF_DIR", str(DEV_TRIANGLE_HOME / "antigravity-handoffs"))
).expanduser()
PATCH_DIR = DEV_TRIANGLE_HOME / "patches"
RESULT_DIR = DEV_TRIANGLE_HOME / "antigravity-results"
ANTIGRAVITY_DEFAULT_PROMPT_ARG = "-p"
ANTIGRAVITY_RESULT_MARKER = "DEV_TRIANGLE_RESULT_READY"
ANTIGRAVITY_LEGACY_UNSAFE_MODELS = {"Gemini 3.5 Flash (Medium)"}


class ToolError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DEV_TRIANGLE_HOME.mkdir(parents=True, exist_ok=True)
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    # NOTE: Ledger writes are atomic enough for this local single-user tool:
    # write a sibling temp file, then replace the target in one filesystem move.
    # This avoids half-written JSON if a process exits during serialization.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def load_ledger() -> dict[str, Any]:
    ledger = read_json(
        LEDGER_PATH,
        {"schemaVersion": 1, "createdAt": now_iso(), "updatedAt": now_iso(), "jobs": [], "handoffs": []},
    )
    ledger.setdefault("jobs", [])
    ledger.setdefault("handoffs", [])
    return ledger


def save_ledger(ledger: dict[str, Any]) -> None:
    ledger["updatedAt"] = now_iso()
    write_json(LEDGER_PATH, ledger)


def short_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


def compact_text(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... truncated ..."


def sanitize_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return value or fallback


def resolve_result_path(value: str | None, handoff: dict[str, Any]) -> Path:
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = RESULT_DIR / path
    else:
        handoff_id = handoff.get("id") or sanitize_filename(str(handoff.get("title", "handoff")), "handoff")
        path = RESULT_DIR / f"{sanitize_filename(str(handoff_id), 'handoff')}-result.md"
    path = path.resolve()
    allowed_roots = [RESULT_DIR.resolve(), HANDOFF_DIR.resolve()]
    if not any(str(path).lower().startswith(str(root).lower()) for root in allowed_roots):
        raise ToolError(f"Result path must be inside {RESULT_DIR} or {HANDOFF_DIR}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_ready_result(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return ANTIGRAVITY_RESULT_MARKER in text, text


def wait_for_result_file(path: Path, timeout_sec: int, poll_interval_sec: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last_text = ""
    while time.monotonic() < deadline:
        ready, text = read_ready_result(path)
        last_text = text
        if ready:
            return {"ready": True, "path": str(path), "content": text, "marker": ANTIGRAVITY_RESULT_MARKER}
        time.sleep(poll_interval_sec)
    return {
        "ready": False,
        "path": str(path),
        "contentTail": last_text[-4000:],
        "marker": ANTIGRAVITY_RESULT_MARKER,
        "message": f"Timed out waiting for {ANTIGRAVITY_RESULT_MARKER}.",
    }


def require_string(args: dict[str, Any], name: str, max_len: int = 20000) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"Missing required string argument: {name}")
    value = value.strip()
    if len(value) > max_len:
        raise ToolError(f"Argument {name} is too long. Max length is {max_len}.")
    return value


def optional_string(args: dict[str, Any], name: str, max_len: int = 20000) -> str | None:
    value = args.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError(f"Argument {name} must be a string.")
    value = value.strip()
    if not value:
        return None
    if len(value) > max_len:
        raise ToolError(f"Argument {name} is too long. Max length is {max_len}.")
    return value


def optional_int(args: dict[str, Any], name: str, default: int, minimum: int, maximum: int) -> int:
    value = args.get(name, default)
    if not isinstance(value, int):
        raise ToolError(f"Argument {name} must be an integer.")
    if value < minimum or value > maximum:
        raise ToolError(f"Argument {name} must be between {minimum} and {maximum}.")
    return value


def optional_string_list(args: dict[str, Any], name: str) -> list[str]:
    value = args.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolError(f"Argument {name} must be a list of strings.")
    return [item.strip() for item in value if item.strip()]


def optional_bool(args: dict[str, Any], name: str, default: bool) -> bool:
    value = args.get(name, default)
    if not isinstance(value, bool):
        raise ToolError(f"Argument {name} must be a boolean.")
    return value


def normalize_session_name(value: str) -> str:
    value = value.strip().strip("/")
    if value.startswith("sessions/"):
        return value
    return f"sessions/{value}"


def session_id_from_name(value: str) -> str:
    return normalize_session_name(value).split("/", 1)[1]


def normalize_source(value: str) -> str:
    value = value.strip().strip("/")
    if value.startswith("sources/"):
        return value
    if value.startswith("github/"):
        return f"sources/{value}"
    parts = value.split("/")
    if len(parts) == 2 and all(parts):
        return f"sources/github/{parts[0]}/{parts[1]}"
    return value


def jules_base_url() -> str:
    return os.environ.get("JULES_BASE_URL", "https://jules.googleapis.com/v1alpha").rstrip("/")


def jules_api_key() -> str:
    key = os.environ.get("JULES_API_KEY", "").strip()
    if not key:
        raise ToolError("JULES_API_KEY is not set. Create a Jules API key and expose it as an environment variable.")
    return key


def http_json(method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            query = "?" + parse.urlencode(clean)

    url = f"{jules_base_url()}{path}{query}"
    data = None
    headers = {"x-goog-api-key": jules_api_key()}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"

    timeout = float(os.environ.get("JULES_TIMEOUT_SEC", "60"))
    req = request.Request(url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        message = raw
        try:
            payload = json.loads(raw)
            message = payload.get("error", {}).get("message") or raw
        except json.JSONDecodeError:
            pass
        raise ToolError(f"Jules API {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise ToolError(f"Jules API connection failed: {exc}") from exc

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"Jules API returned non-JSON response: {raw[:500]}") from exc


DEFAULT_JULES_GITIGNORE_LINES = [
    ".env",
    ".env.*",
    "!.env.example",
    ".dev-triangle/",
    ".dev-triangle-test/",
    ".dev-triangle-report-test/",
    "demo-output/",
    "logs/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "node_modules/",
    ".venv/",
    "venv/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
]

SCAN_EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    "dist",
    "build",
    "target",
    ".dev-triangle",
    ".dev-triangle-test",
    ".dev-triangle-report-test",
    "demo-output",
    "logs",
}

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


def run_native(command: list[str], cwd: Path | None = None, timeout: int = 60, allow_failure: bool = False) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out after {timeout}s: {' '.join(command)}") from exc

    result = {
        "command": command,
        "exitCode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0 and not allow_failure:
        stderr = (proc.stderr or proc.stdout or "").strip()
        raise ToolError(f"Command failed ({proc.returncode}): {' '.join(command)}\n{stderr[-2000:]}")
    return result


def resolve_project_dir(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise ToolError(f"Project path does not exist: {path}")
    if not path.is_dir():
        raise ToolError(f"Project path must be a directory: {path}")
    return path


def is_git_repo(repo_path: Path) -> bool:
    result = run_native(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path, allow_failure=True)
    return result["exitCode"] == 0 and result["stdout"].strip() == "true"


def git_has_commits(repo_path: Path) -> bool:
    return run_native(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_path, allow_failure=True)["exitCode"] == 0


def git_current_branch(repo_path: Path) -> str | None:
    result = run_native(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, allow_failure=True)
    branch = result["stdout"].strip()
    if result["exitCode"] != 0 or not branch or branch == "HEAD":
        return None
    return branch


def git_status_porcelain(repo_path: Path) -> str:
    return run_native(["git", "status", "--porcelain"], cwd=repo_path)["stdout"]


def git_dirty_paths(status_text: str) -> list[str]:
    paths: list[str] = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        paths.append(path.strip('"'))
    return paths


def ensure_git_identity(repo_path: Path) -> None:
    if run_native(["git", "config", "user.name"], cwd=repo_path, allow_failure=True)["exitCode"] != 0:
        run_native(["git", "config", "user.name", "Dev Triangle MCP"], cwd=repo_path)
    if run_native(["git", "config", "user.email"], cwd=repo_path, allow_failure=True)["exitCode"] != 0:
        run_native(["git", "config", "user.email", "dev-triangle-mcp@users.noreply.github.com"], cwd=repo_path)


def git_remote_url(repo_path: Path, remote_name: str) -> str | None:
    result = run_native(["git", "remote", "get-url", remote_name], cwd=repo_path, allow_failure=True)
    if result["exitCode"] != 0:
        return None
    return result["stdout"].strip() or None


def github_owner_repo_from_remote(remote_url: str | None) -> str | None:
    if not remote_url:
        return None
    match = re.search(r"github\.com[:/](?P<owner>[^/\s:]+)/(?P<repo>[^/\s]+?)(?:\.git)?/?$", remote_url.strip())
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    return f"{owner}/{repo}"


def sanitize_github_repo_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    name = re.sub(r"-{2,}", "-", name)
    if not name:
        raise ToolError("Could not derive a GitHub repository name.")
    if len(name) > 100:
        name = name[:100].rstrip(".-")
    return name


def gh_current_owner() -> str:
    result = run_native(["gh", "api", "user", "--jq", ".login"], timeout=30)
    owner = result["stdout"].strip()
    if not owner:
        raise ToolError("Could not determine the authenticated GitHub owner from gh.")
    return owner


def gh_repo_exists(full_name: str) -> dict[str, Any] | None:
    result = run_native(
        ["gh", "repo", "view", full_name, "--json", "nameWithOwner,isPrivate,url"],
        timeout=30,
        allow_failure=True,
    )
    if result["exitCode"] != 0:
        return None
    try:
        return json.loads(result["stdout"])
    except json.JSONDecodeError:
        return {"nameWithOwner": full_name}


def ensure_default_gitignore(repo_path: Path, dry_run: bool) -> list[str]:
    gitignore = repo_path / ".gitignore"
    existing = ""
    if gitignore.exists():
        existing = gitignore.read_text(encoding="utf-8", errors="replace")
    existing_lines = {line.strip() for line in existing.splitlines()}
    missing = [line for line in DEFAULT_JULES_GITIGNORE_LINES if line not in existing_lines]
    if missing and not dry_run:
        prefix = "" if not existing or existing.endswith(("\n", "\r")) else "\n"
        block = "\n# Dev Triangle MCP safety defaults\n" + "\n".join(missing) + "\n"
        gitignore.write_text(existing + prefix + block, encoding="utf-8")
    return missing


def git_path_is_ignored(repo_path: Path, rel_path: str) -> bool:
    result = run_native(["git", "check-ignore", "-q", "--", rel_path], cwd=repo_path, allow_failure=True)
    return result["exitCode"] == 0


def git_path_is_tracked(repo_path: Path, rel_path: str) -> bool:
    result = run_native(["git", "ls-files", "--error-unmatch", "--", rel_path], cwd=repo_path, allow_failure=True)
    return result["exitCode"] == 0


def iter_scannable_files(repo_path: Path, max_files: int) -> tuple[list[Path], bool]:
    files: list[Path] = []
    truncated = False
    for root, dirs, names in os.walk(repo_path):
        dirs[:] = [name for name in dirs if name not in SCAN_EXCLUDED_DIRS]
        for name in names:
            path = Path(root) / name
            if not path.is_file():
                continue
            files.append(path)
            if len(files) >= max_files:
                return files, True
    return files, truncated


def is_probably_text(path: Path, max_bytes: int = 1_000_000) -> bool:
    try:
        if path.stat().st_size > max_bytes:
            return False
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" not in sample


def scan_repo_for_publish_safety(repo_path: Path, max_files: int = 3000) -> dict[str, Any]:
    files, truncated = iter_scannable_files(repo_path, max_files)
    git_repo = is_git_repo(repo_path)
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for path in files:
        rel = path.relative_to(repo_path).as_posix()
        ignored = git_path_is_ignored(repo_path, rel) if git_repo else False
        tracked = git_path_is_tracked(repo_path, rel) if git_repo else False
        should_block = tracked or not ignored

        if path.name.lower() != ".env.example" and any(pattern.match(path.name) for pattern in SENSITIVE_FILE_NAME_PATTERNS):
            finding = {"path": rel, "type": "sensitive_filename", "ignored": ignored, "tracked": tracked}
            (blocking if should_block else warnings).append(finding)
            continue

        if is_probably_text(path):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for pattern_name, pattern in SECRET_CONTENT_PATTERNS:
                if pattern.search(text):
                    finding = {
                        "path": rel,
                        "type": "secret_pattern",
                        "pattern": pattern_name,
                        "ignored": ignored,
                        "tracked": tracked,
                    }
                    (blocking if should_block else warnings).append(finding)
                    break

        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > 50 * 1024 * 1024 and (tracked or not ignored):
            warnings.append({"path": rel, "type": "large_file", "bytes": size, "ignored": ignored, "tracked": tracked})

    return {
        "scannedFiles": len(files),
        "truncated": truncated,
        "blockingFindings": blocking,
        "warnings": warnings,
    }


def tool_prepare_jules_repo(args: dict[str, Any]) -> dict[str, Any]:
    repo_path = resolve_project_dir(require_string(args, "repoPath", 2000))
    publish = optional_bool(args, "publish", False)
    confirm_publish = optional_bool(args, "confirmPublish", False)
    create_remote = optional_bool(args, "createRemote", True)
    push = optional_bool(args, "push", publish)
    commit_changes = optional_bool(args, "commitChanges", False)
    check_jules_source = optional_bool(args, "checkJulesSource", False)
    visibility = optional_string(args, "visibility", 20) or "private"
    if visibility not in {"private", "public", "internal"}:
        raise ToolError("visibility must be private, public, or internal.")
    if visibility == "public" and not optional_bool(args, "confirmPublic", False):
        raise ToolError("Creating a public repo requires confirmPublic=true. The safe default is private.")
    if publish and not confirm_publish:
        raise ToolError("Publishing a local project requires confirmPublish=true.")

    remote_name = optional_string(args, "remoteName", 100) or "origin"
    branch_arg = optional_string(args, "branch", 200)
    repo_name = sanitize_github_repo_name(optional_string(args, "repoName", 200) or repo_path.name)
    github_owner = optional_string(args, "githubOwner", 200)
    commit_message = optional_string(args, "commitMessage", 300) or "Prepare project for Jules"

    run_native(["git", "--version"], timeout=30)
    actions: list[str] = []
    initial_git_repo = is_git_repo(repo_path)
    gitignore_missing = ensure_default_gitignore(repo_path, dry_run=not publish)
    if gitignore_missing:
        actions.append(("would add" if not publish else "added") + " Dev Triangle safety entries to .gitignore")

    if publish and not initial_git_repo:
        branch_for_init = branch_arg or "main"
        init = run_native(["git", "init", "-b", branch_for_init], cwd=repo_path, allow_failure=True)
        if init["exitCode"] != 0:
            run_native(["git", "init"], cwd=repo_path)
            run_native(["git", "checkout", "-B", branch_for_init], cwd=repo_path)
        actions.append(f"initialized git repository on {branch_for_init}")

    git_repo = is_git_repo(repo_path)
    safety = scan_repo_for_publish_safety(repo_path)
    if publish and safety["blockingFindings"]:
        return {
            "status": "BLOCKED",
            "reason": "Potential secrets or sensitive files would be published. Fix .gitignore, untrack the files, or remove the secrets first.",
            "repoPath": str(repo_path),
            "publish": publish,
            "git": {"isRepo": git_repo, "wasRepo": initial_git_repo},
            "safety": safety,
            "actions": actions,
        }

    existing_remote_url = git_remote_url(repo_path, remote_name) if git_repo else None
    existing_source = github_owner_repo_from_remote(existing_remote_url)
    current_branch = git_current_branch(repo_path) if git_repo else None
    branch = branch_arg or current_branch or "main"

    if not publish:
        planned_owner = github_owner or (existing_source.split("/", 1)[0] if existing_source else None)
        planned_full_name = f"{planned_owner}/{repo_name}" if planned_owner else None
        return {
            "status": "DRY_RUN",
            "repoPath": str(repo_path),
            "publish": False,
            "git": {
                "isRepo": git_repo,
                "branch": current_branch,
                "remoteName": remote_name,
                "remoteUrl": existing_remote_url,
                "githubSource": existing_source,
                "dirty": bool(git_status_porcelain(repo_path).strip()) if git_repo else None,
            },
            "github": {
                "plannedOwner": planned_owner,
                "plannedRepo": repo_name,
                "plannedFullName": planned_full_name,
                "visibility": visibility,
            },
            "jules": {
                "source": existing_source or planned_full_name,
                "normalizedSource": normalize_source(existing_source or planned_full_name) if (existing_source or planned_full_name) else None,
                "note": "Run again with publish=true and confirmPublish=true to create/push the repo.",
            },
            "safety": safety,
            "actions": actions or ["dry-run only; no files, remotes, commits, or GitHub repos were changed"],
        }

    if not git_repo:
        raise ToolError("Expected git repository after initialization, but git is not available in the project path.")

    has_commits = git_has_commits(repo_path)
    status_text = git_status_porcelain(repo_path)
    dirty = bool(status_text.strip())
    if not has_commits:
        run_native(["git", "add", "-A"], cwd=repo_path)
        staged = run_native(["git", "diff", "--cached", "--quiet"], cwd=repo_path, allow_failure=True)
        if staged["exitCode"] != 0:
            ensure_git_identity(repo_path)
            run_native(["git", "commit", "-m", commit_message], cwd=repo_path, timeout=120)
            actions.append("created initial commit")
    elif dirty:
        dirty_paths = git_dirty_paths(status_text)
        only_safety_gitignore = bool(dirty_paths) and all(path == ".gitignore" for path in dirty_paths)
        if not commit_changes and not only_safety_gitignore:
            return {
                "status": "BLOCKED",
                "reason": "Existing repo has uncommitted changes. Commit them yourself or rerun with commitChanges=true.",
                "repoPath": str(repo_path),
                "publish": publish,
                "git": {"isRepo": True, "branch": branch, "dirty": True},
                "safety": safety,
                "actions": actions,
            }
        run_native(["git", "add", "-A"], cwd=repo_path)
        staged = run_native(["git", "diff", "--cached", "--quiet"], cwd=repo_path, allow_failure=True)
        if staged["exitCode"] != 0:
            ensure_git_identity(repo_path)
            run_native(["git", "commit", "-m", commit_message], cwd=repo_path, timeout=120)
            actions.append("committed safety .gitignore defaults" if only_safety_gitignore else "committed existing dirty worktree changes")

    remote_url = git_remote_url(repo_path, remote_name)
    source = github_owner_repo_from_remote(remote_url)
    repo_created = False
    if not remote_url:
        if not create_remote:
            return {
                "status": "BLOCKED",
                "reason": f"No git remote named {remote_name}. Rerun with createRemote=true or add a GitHub remote.",
                "repoPath": str(repo_path),
                "publish": publish,
                "git": {"isRepo": True, "branch": branch, "remoteName": remote_name},
                "safety": safety,
                "actions": actions,
            }
        owner = github_owner or gh_current_owner()
        full_name = f"{owner}/{repo_name}"
        existing_repo = gh_repo_exists(full_name)
        if not existing_repo:
            flag = {"private": "--private", "public": "--public", "internal": "--internal"}[visibility]
            run_native(["gh", "repo", "create", full_name, flag], timeout=60)
            repo_created = True
            actions.append(f"created GitHub {visibility} repo {full_name}")
        remote_url = f"https://github.com/{full_name}.git"
        run_native(["git", "remote", "add", remote_name, remote_url], cwd=repo_path)
        source = full_name
        actions.append(f"added git remote {remote_name}")

    if push:
        run_native(["git", "push", "-u", remote_name, branch], cwd=repo_path, timeout=180)
        actions.append(f"pushed {branch} to {remote_name}")

    jules: dict[str, Any] = {
        "source": source,
        "normalizedSource": normalize_source(source) if source else None,
        "apiKeyPresent": bool(os.environ.get("JULES_API_KEY", "").strip()),
    }
    if check_jules_source:
        if not jules["apiKeyPresent"]:
            jules["visible"] = None
            jules["visibilityNote"] = "JULES_API_KEY is not set, so source visibility was not checked."
        else:
            try:
                sources = http_json("GET", "/sources", params={"pageSize": 100}).get("sources", [])
                normalized = jules["normalizedSource"]
                names = [item.get("name") for item in sources]
                jules["visible"] = normalized in names or source in names
                jules["sourceCount"] = len(sources)
            except ToolError as exc:
                jules["visible"] = None
                jules["visibilityError"] = str(exc)

    return {
        "status": "READY_FOR_JULES" if source else "PUBLISHED_WITHOUT_GITHUB_SOURCE",
        "repoPath": str(repo_path),
        "publish": True,
        "git": {
            "isRepo": True,
            "branch": branch,
            "remoteName": remote_name,
            "remoteUrl": git_remote_url(repo_path, remote_name),
            "dirty": bool(git_status_porcelain(repo_path).strip()),
        },
        "github": {"source": source, "repoCreated": repo_created, "visibility": visibility},
        "jules": jules,
        "safety": safety,
        "actions": actions,
    }


def upsert_job(job: dict[str, Any]) -> dict[str, Any]:
    # Jules and future providers may report different stable identifiers. Keep
    # local IDs stable when possible by matching either the local id or the
    # provider's external session name.
    ledger = load_ledger()
    jobs = ledger["jobs"]
    existing = None
    for item in jobs:
        if item.get("id") == job.get("id"):
            existing = item
            break
        external = item.get("external", {})
        if job.get("external", {}).get("name") and external.get("name") == job["external"]["name"]:
            existing = item
            break
    if existing:
        existing.update(job)
        existing["updatedAt"] = now_iso()
        saved = existing
    else:
        job.setdefault("id", short_id(job.get("provider", "job")))
        job.setdefault("createdAt", now_iso())
        job["updatedAt"] = now_iso()
        jobs.append(job)
        saved = job
    save_ledger(ledger)
    return saved


def update_job_by_session(session: dict[str, Any]) -> dict[str, Any] | None:
    name = session.get("name")
    sid = session.get("id")
    if not name and not sid:
        return None
    ledger = load_ledger()
    matched = None
    for job in ledger["jobs"]:
        external = job.get("external", {})
        if external.get("name") == name or external.get("id") == sid:
            matched = job
            break
    if matched is None:
        matched = {
            "id": short_id("jules"),
            "provider": "jules",
            "title": session.get("title") or name or sid,
            "createdAt": now_iso(),
        }
        ledger["jobs"].append(matched)
    matched["status"] = session.get("state", matched.get("status", "UNKNOWN"))
    matched["updatedAt"] = now_iso()
    matched["external"] = {
        "name": name,
        "id": sid,
        "url": session.get("url"),
        "outputs": session.get("outputs", []),
    }
    save_ledger(ledger)
    return matched


def tool_jules_list_sources(args: dict[str, Any]) -> dict[str, Any]:
    # Jules tools are thin REST wrappers plus local ledger bookkeeping. They do
    # not run local code; local verification is delegated to Antigravity.
    params = {
        "pageSize": optional_int(args, "pageSize", 30, 1, 100),
        "pageToken": optional_string(args, "pageToken", 2000),
        "filter": optional_string(args, "filter", 2000),
    }
    payload = http_json("GET", "/sources", params=params)
    return {"sources": payload.get("sources", []), "nextPageToken": payload.get("nextPageToken")}


def tool_jules_list_sessions(args: dict[str, Any]) -> dict[str, Any]:
    params = {
        "pageSize": optional_int(args, "pageSize", 20, 1, 100),
        "pageToken": optional_string(args, "pageToken", 2000),
    }
    payload = http_json("GET", "/sessions", params=params)
    return {"sessions": payload.get("sessions", []), "nextPageToken": payload.get("nextPageToken")}


def jules_default_branch_for_source(source_name: str) -> str | None:
    page_token: str | None = None
    for _ in range(10):
        payload = http_json("GET", "/sources", params={"pageSize": 100, "pageToken": page_token})
        for source in payload.get("sources", []):
            if source.get("name") != source_name and source.get("id") != source_name.removeprefix("sources/"):
                continue
            github_repo = source.get("githubRepo") or {}
            default_branch = github_repo.get("defaultBranch") or {}
            branch = default_branch.get("displayName")
            return branch if isinstance(branch, str) and branch.strip() else None
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return None


def tool_jules_create_session(args: dict[str, Any]) -> dict[str, Any]:
    prompt = require_string(args, "prompt", 40000)
    title = optional_string(args, "title", 200)
    source = optional_string(args, "source", 500)
    starting_branch = optional_string(args, "startingBranch", 200)
    automation_mode = optional_string(args, "automationMode", 100)
    require_plan_approval = args.get("requirePlanApproval", True)
    if not isinstance(require_plan_approval, bool):
        raise ToolError("Argument requirePlanApproval must be a boolean.")

    body: dict[str, Any] = {"prompt": prompt, "requirePlanApproval": require_plan_approval}
    if title:
        body["title"] = title
    if source:
        normalized_source = normalize_source(source)
        source_context: dict[str, Any] = {"source": normalized_source}
        if normalized_source.startswith("sources/github/"):
            branch = starting_branch or jules_default_branch_for_source(normalized_source) or "main"
            source_context["githubRepoContext"] = {"startingBranch": branch}
        body["sourceContext"] = source_context
    if automation_mode:
        body["automationMode"] = automation_mode

    session = http_json("POST", "/sessions", body=body)
    job = upsert_job(
        {
            "id": short_id("jules"),
            "provider": "jules",
            "title": session.get("title") or title or "Jules session",
            "status": session.get("state", "QUEUED"),
            "prompt": prompt,
            "external": {
                "name": session.get("name"),
                "id": session.get("id"),
                "url": session.get("url"),
                "source": normalize_source(source) if source else None,
            },
        }
    )
    return {"job": job, "session": session}


def tool_jules_get_session(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    session = http_json("GET", f"/{session_name}")
    job = update_job_by_session(session)
    return {"job": job, "session": session}


def tool_jules_list_activities(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    params = {
        "pageSize": optional_int(args, "pageSize", 50, 1, 100),
        "pageToken": optional_string(args, "pageToken", 2000),
        "createTime": optional_string(args, "createTime", 200),
    }
    payload = http_json("GET", f"/{session_name}/activities", params=params)
    return {"activities": payload.get("activities", []), "nextPageToken": payload.get("nextPageToken")}


def tool_jules_send_message(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    prompt = require_string(args, "prompt", 20000)
    payload = http_json("POST", f"/{session_name}:sendMessage", body={"prompt": prompt})
    return {"session": session_name, "sent": True, "response": payload}


def tool_jules_approve_plan(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    payload = http_json("POST", f"/{session_name}:approvePlan", body={})
    return {"session": session_name, "approved": True, "response": payload}


def extract_patches_from_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patches: list[dict[str, Any]] = []
    for activity in activities:
        for artifact in activity.get("artifacts", []) or []:
            change_set = artifact.get("changeSet")
            if not isinstance(change_set, dict):
                continue
            git_patch = change_set.get("gitPatch")
            if not isinstance(git_patch, dict):
                continue
            patch_text = git_patch.get("unidiffPatch")
            if isinstance(patch_text, str) and patch_text:
                patches.append(
                    {
                        "activity": activity.get("name"),
                        "createTime": activity.get("createTime"),
                        "source": change_set.get("source"),
                        "baseCommitId": git_patch.get("baseCommitId"),
                        "suggestedCommitMessage": git_patch.get("suggestedCommitMessage"),
                        "unidiffPatch": patch_text,
                    }
                )
    return patches


def tool_jules_get_outputs(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    include_patches = args.get("includePatches", False)
    if not isinstance(include_patches, bool):
        raise ToolError("Argument includePatches must be a boolean.")
    session = http_json("GET", f"/{session_name}")
    job = update_job_by_session(session)
    result: dict[str, Any] = {"job": job, "session": session, "outputs": session.get("outputs", [])}
    if include_patches:
        activities_payload = http_json("GET", f"/{session_name}/activities", params={"pageSize": 100})
        result["patches"] = extract_patches_from_activities(activities_payload.get("activities", []))
    return result


def tool_jules_save_latest_patch(args: dict[str, Any]) -> dict[str, Any]:
    session_name = normalize_session_name(require_string(args, "session", 300))
    requested_name = optional_string(args, "fileName", 200)
    activities_payload = http_json("GET", f"/{session_name}/activities", params={"pageSize": 100})
    patches = extract_patches_from_activities(activities_payload.get("activities", []))
    if not patches:
        raise ToolError(f"No git patch artifacts found for {session_name}.")

    latest = patches[-1]
    default_name = f"{session_id_from_name(session_name)}.patch"
    file_name = sanitize_filename(requested_name or default_name, default_name)
    path = PATCH_DIR / file_name
    path.write_text(latest["unidiffPatch"], encoding="utf-8")
    return {
        "session": session_name,
        "patchPath": str(path.resolve()),
        "baseCommitId": latest.get("baseCommitId"),
        "suggestedCommitMessage": latest.get("suggestedCommitMessage"),
        "activity": latest.get("activity"),
    }


def tool_create_antigravity_handoff(args: dict[str, Any]) -> dict[str, Any]:
    objective = require_string(args, "objective", 20000)
    title = optional_string(args, "title", 200) or "Antigravity local verification"
    repo_path = optional_string(args, "repoPath", 2000)
    context = optional_string(args, "context", 20000)
    source_job_id = optional_string(args, "sourceJobId", 200)
    files = optional_string_list(args, "files")
    suggested_commands = optional_string_list(args, "suggestedCommands")
    acceptance = optional_string(args, "acceptanceCriteria", 10000)

    handoff_id = short_id("antigravity")
    file_name = sanitize_filename(f"{handoff_id}-{title}.md", f"{handoff_id}.md")
    path = HANDOFF_DIR / file_name

    lines = [
        f"# {title}",
        "",
        "## Objective",
        objective,
        "",
        "## Metadata",
        f"- handoffId: {handoff_id}",
        f"- createdAt: {now_iso()}",
        f"- sourceJobId: {source_job_id or ''}",
        f"- repoPath: {repo_path or ''}",
        "",
    ]
    if context:
        lines += ["## Context", context, ""]
    if files:
        lines += ["## Files", *[f"- {item}" for item in files], ""]
    if suggested_commands:
        lines += ["## Suggested Commands", *[f"- `{item}`" for item in suggested_commands], ""]
    if acceptance:
        lines += ["## Acceptance Criteria", acceptance, ""]
    lines += [
        "## Suggested Antigravity Prompt",
        "Read this handoff file, work in the listed repo, run the local verification loop, and write back a short result summary.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    ledger = load_ledger()
    handoff = {
        "id": handoff_id,
        "provider": "antigravity",
        "title": title,
        "status": "READY",
        "path": str(path.resolve()),
        "repoPath": repo_path,
        "sourceJobId": source_job_id,
        "createdAt": now_iso(),
        "updatedAt": now_iso(),
    }
    ledger["handoffs"].append(handoff)
    save_ledger(ledger)

    return {
        "handoff": handoff,
        "suggestedPrompt": f"Use the handoff at {path.resolve()} and complete the local verification loop.",
    }


def find_handoff_by_id_or_path(value: str) -> dict[str, Any]:
    ledger = load_ledger()
    for handoff in ledger.get("handoffs", []):
        if handoff.get("id") == value or handoff.get("path") == value:
            return handoff
    path = Path(value).expanduser()
    if path.exists():
        return {
            "id": None,
            "provider": "antigravity",
            "title": path.stem,
            "status": "EXTERNAL",
            "path": str(path.resolve()),
            "repoPath": None,
        }
    raise ToolError(f"No handoff found for {value}.")


def update_handoff(handoff_id: str | None, updates: dict[str, Any]) -> dict[str, Any] | None:
    if not handoff_id:
        return None
    ledger = load_ledger()
    for handoff in ledger.get("handoffs", []):
        if handoff.get("id") == handoff_id:
            handoff.update(updates)
            handoff["updatedAt"] = now_iso()
            save_ledger(ledger)
            return handoff
    return None


def antigravity_candidates() -> list[str]:
    configured = os.environ.get("ANTIGRAVITY_COMMAND", "").strip()
    candidates = [configured] if configured else []
    local_appdata = Path(os.environ.get("LOCALAPPDATA", "")).expanduser()
    candidates += [
        "agy",
        "agy.exe",
        str(local_appdata / "agy" / "bin" / "agy.exe"),
        "antigravity",
        "antigravity-cli",
        "antigravity-ide",
        "antigravity-ide.cmd",
        str(local_appdata / "Programs" / "Antigravity IDE" / "bin" / "antigravity-ide.cmd"),
        str(local_appdata / "Programs" / "Antigravity IDE" / "bin" / "antigravity-ide"),
        str(local_appdata / "Programs" / "antigravity" / "Antigravity.exe"),
    ]
    seen: set[str] = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


def resolve_antigravity_command(command_override: str | None = None) -> dict[str, Any]:
    candidates = [command_override] if command_override else antigravity_candidates()
    checked: list[dict[str, Any]] = []
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            resolved = str(path.resolve())
            checked.append({"candidate": candidate, "resolved": resolved, "available": True})
            return {"available": True, "command": resolved, "checked": checked}
        found = shutil.which(candidate)
        if found:
            checked.append({"candidate": candidate, "resolved": found, "available": True})
            return {"available": True, "command": found, "checked": checked}
        checked.append({"candidate": candidate, "available": False})
    return {"available": False, "command": None, "checked": checked}


def tool_antigravity_detect_cli(args: dict[str, Any]) -> dict[str, Any]:
    command = optional_string(args, "command", 2000)
    smoke_print = args.get("smokePrint", False)
    if not isinstance(smoke_print, bool):
        raise ToolError("Argument smokePrint must be a boolean.")
    smoke_timeout_sec = optional_int(args, "smokeTimeoutSec", 30, 5, 120)
    detected = resolve_antigravity_command(command)
    command_kind = antigravity_command_kind(detected["command"])
    agy_model, agy_model_note = configured_antigravity_agy_model()
    payload = {
        "available": detected["available"],
        "command": detected["command"],
        "commandKind": command_kind,
        "checked": detected["checked"],
        "promptArg": os.environ.get("ANTIGRAVITY_PROMPT_ARG", ANTIGRAVITY_DEFAULT_PROMPT_ARG),
        "agyModel": agy_model,
        "agyModelNote": agy_model_note,
        "note": (
            "Set ANTIGRAVITY_COMMAND to the full Antigravity CLI path if auto-detection fails."
            if not detected["available"]
            else (
                "agy CLI is the preferred headless path."
                if command_kind == "agy_cli"
                else "Antigravity IDE chat launches a UI chat; this launcher does not expose completion capture."
            )
        ),
    }
    if smoke_print:
        payload["printSmoke"] = run_antigravity_print_smoke(detected["command"], smoke_timeout_sec)
    return payload


def configured_antigravity_agy_model() -> tuple[str, str | None]:
    model = os.environ.get("ANTIGRAVITY_AGY_MODEL", "").strip()
    if not model:
        return "", None
    if model in ANTIGRAVITY_LEGACY_UNSAFE_MODELS:
        return "", f"Ignored legacy unsafe ANTIGRAVITY_AGY_MODEL value: {model}"
    return model, None


def antigravity_command_kind(command: str | None) -> str:
    if not command:
        return "unknown"
    name = Path(command).name.lower()
    if name in {"agy", "agy.exe"}:
        return "agy_cli"
    if "antigravity-ide" in name:
        return "ide_chat"
    if name == "antigravity.exe":
        return "desktop_app"
    return "prompt_arg"


def build_antigravity_command_line(
    command: str,
    prompt: str,
    prompt_arg: str,
    mode: str,
    window_mode: str,
    execution_style: str,
) -> tuple[list[str], str]:
    # NOTE: agy_print is the preferred unattended path. The older
    # antigravity-ide.cmd chat route can launch a UI but did not reliably return
    # a completed agent result in local testing.
    kind = antigravity_command_kind(command)
    style = execution_style
    if style == "auto":
        if kind == "agy_cli":
            style = "agy_print"
        elif kind == "ide_chat":
            style = "ide_chat"
        else:
            style = "prompt_arg"

    if style == "agy_print":
        model, _ = configured_antigravity_agy_model()
        timeout = os.environ.get("ANTIGRAVITY_AGY_PRINT_TIMEOUT", "30m")
        command_line = [command]
        if os.environ.get("ANTIGRAVITY_AGY_NEW_PROJECT", "0") not in {"0", "false", "False"}:
            command_line.append("--new-project")
        if model:
            command_line += ["--model", model]
        command_line += ["--print", prompt, "--print-timeout", timeout]
        if os.environ.get("ANTIGRAVITY_AGY_SKIP_PERMISSIONS", "1") not in {"0", "false", "False"}:
            command_line.append("--dangerously-skip-permissions")
        return command_line, style

    if style == "ide_chat":
        if mode not in {"ask", "edit", "agent"}:
            raise ToolError("Argument mode must be ask, edit, or agent for Antigravity IDE chat.")
        if window_mode not in {"default", "new", "reuse"}:
            raise ToolError("Argument windowMode must be default, new, or reuse.")
        command_line = [command, "chat", "--mode", mode]
        if window_mode == "new":
            command_line.append("--new-window")
        elif window_mode == "reuse":
            command_line.append("--reuse-window")
        command_line.append(prompt)
        return command_line, style

    if style == "prompt_arg":
        return [command, prompt_arg, prompt], style

    raise ToolError("Argument executionStyle must be auto, agy_print, ide_chat, or prompt_arg.")


def antigravity_subprocess_env(command: str) -> dict[str, str]:
    # agy may need GNU grep on Windows for its internal search steps. Git for
    # Windows commonly provides it, so we prepend that location when present.
    env = os.environ.copy()
    extra_paths: list[str] = []
    command_parent = str(Path(command).expanduser().parent)
    if command_parent and command_parent != ".":
        extra_paths.append(command_parent)
    git_grep = Path(r"C:\Program Files\Git\usr\bin")
    if git_grep.exists():
        extra_paths.append(str(git_grep))
    current_path = env.get("PATH", "")
    existing = {item.lower() for item in current_path.split(os.pathsep) if item}
    for item in reversed(extra_paths):
        if item.lower() not in existing:
            current_path = item + os.pathsep + current_path
    env["PATH"] = current_path
    return env


def run_antigravity_print_smoke(command: str | None, timeout_sec: int) -> dict[str, Any]:
    if not command:
        return {"ran": False, "passed": False, "reason": "Antigravity command is unavailable."}
    if antigravity_command_kind(command) != "agy_cli":
        return {"ran": False, "passed": False, "reason": "Print smoke only supports agy CLI."}

    expected = "DEV_TRIANGLE_AGY_SMOKE_OK"
    command_line: list[str] = [command]
    if os.environ.get("ANTIGRAVITY_AGY_NEW_PROJECT", "0") not in {"0", "false", "False"}:
        command_line.append("--new-project")
    agy_model, agy_model_note = configured_antigravity_agy_model()
    if agy_model:
        command_line += ["--model", agy_model]
    command_line += [
        "--print",
        f"Reply with exactly: {expected}",
        "--print-timeout",
        f"{timeout_sec}s",
    ]
    if os.environ.get("ANTIGRAVITY_AGY_SKIP_PERMISSIONS", "1") != "0":
        command_line.append("--dangerously-skip-permissions")

    try:
        completed = subprocess.run(
            command_line,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec + 15,
            env=antigravity_subprocess_env(command),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ran": True,
            "passed": False,
            "timedOut": True,
            "timeoutSec": timeout_sec,
            "stdoutNonEmpty": bool((exc.stdout or "").strip()),
            "stderrNonEmpty": bool((exc.stderr or "").strip()),
            "modelNote": agy_model_note,
        }

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return {
        "ran": True,
        "passed": completed.returncode == 0 and expected in stdout,
        "exitCode": completed.returncode,
        "stdoutNonEmpty": bool(stdout.strip()),
        "stderrNonEmpty": bool(stderr.strip()),
        "expectedTokenFound": expected in stdout,
        "modelNote": agy_model_note,
        "stdoutTail": stdout[-500:],
        "stderrTail": stderr[-500:],
    }


def tool_run_antigravity_handoff(args: dict[str, Any]) -> dict[str, Any]:
    # This is the local validation bridge:
    # 1. Find a prepared handoff markdown file.
    # 2. Launch a known Antigravity CLI command.
    # 3. Wait for either report-only MCP submission or mailbox marker output.
    #
    # It is intentionally not a general shell runner.
    handoff_ref = require_string(args, "handoff", 2000)
    command = optional_string(args, "command", 2000)
    repo_path_override = optional_string(args, "repoPath", 2000)
    prompt_arg = optional_string(args, "promptArg", 50) or os.environ.get(
        "ANTIGRAVITY_PROMPT_ARG", ANTIGRAVITY_DEFAULT_PROMPT_ARG
    )
    mode = optional_string(args, "mode", 50) or os.environ.get("ANTIGRAVITY_CHAT_MODE", "agent")
    window_mode = optional_string(args, "windowMode", 50) or os.environ.get("ANTIGRAVITY_WINDOW_MODE", "new")
    execution_style = optional_string(args, "executionStyle", 50) or os.environ.get(
        "ANTIGRAVITY_EXECUTION_STYLE", "auto"
    )
    timeout_sec = optional_int(args, "timeoutSec", 1800, 30, 14400)
    result_timeout_sec = optional_int(args, "resultTimeoutSec", 1800, 10, 14400)
    empty_stdout_result_grace_sec = optional_int(args, "emptyStdoutResultGraceSec", 15, 1, 300)
    poll_interval_sec = optional_int(args, "pollIntervalSec", 5, 1, 120)
    result_path_arg = optional_string(args, "resultPath", 2000)
    dry_run = args.get("dryRun", False)
    if not isinstance(dry_run, bool):
        raise ToolError("Argument dryRun must be a boolean.")
    wait_for_result = args.get("waitForResult", False)
    if not isinstance(wait_for_result, bool):
        raise ToolError("Argument waitForResult must be a boolean.")

    handoff = find_handoff_by_id_or_path(handoff_ref)
    handoff_path = Path(str(handoff["path"])).expanduser()
    if not handoff_path.exists():
        raise ToolError(f"Handoff file does not exist: {handoff_path}")

    repo_path = Path(repo_path_override or handoff.get("repoPath") or handoff_path.parent).expanduser()
    if not repo_path.exists():
        raise ToolError(f"Repo path does not exist: {repo_path}")

    result_path = resolve_result_path(result_path_arg, handoff)
    if result_path.exists() and not dry_run:
        result_path.unlink()

    prompt = (
        f"Use the handoff at {handoff_path.resolve()} and complete the local verification loop. "
        "Write a concise result summary with commands run, pass/fail status, and merge recommendation. "
        "Closed-loop reporting contract: "
        "If the dev-triangle-report MCP tool complete_dev_triangle_handoff is available, call it first with handoff, status, recommendation, summary, commandsRun, findings, and followUps; "
        "otherwise, if the dev-triangle MCP tool submit_antigravity_result is available, call it with the final status, recommendation, summary, commandsRun, findings, and followUps; "
        "if MCP tool submission is unavailable, use the file fallback; "
        f"RESULT_PATH: {result_path}; "
        "When and only when the verification is complete, write the final report to RESULT_PATH; "
        f"End the report with this exact marker on its own line: {ANTIGRAVITY_RESULT_MARKER}; "
        "Include status, recommendation, commands run, test results, findings, and any follow-up needed; "
        "Do not mark the result ready until the local verification loop is actually complete."
    )
    detected = resolve_antigravity_command(command)
    resolved_command = detected["command"] or (command or "antigravity")
    command_line, resolved_style = build_antigravity_command_line(
        resolved_command,
        prompt,
        prompt_arg,
        mode,
        window_mode,
        execution_style,
    )

    if dry_run:
        return {
            "handoff": handoff,
            "repoPath": str(repo_path.resolve()),
            "available": detected["available"],
            "checked": detected["checked"],
            "commandLine": command_line,
            "commandKind": antigravity_command_kind(detected["command"]),
            "executionStyle": resolved_style,
            "completionCapture": resolved_style != "ide_chat",
            "waitForResult": wait_for_result,
            "resultPath": str(result_path),
            "resultMarker": ANTIGRAVITY_RESULT_MARKER,
            "dryRun": True,
        }

    if not detected["available"]:
        update_handoff(
            handoff.get("id"),
            {
                "status": "BLOCKED_NO_ANTIGRAVITY_CLI",
                "lastRun": {
                    "at": now_iso(),
                    "available": False,
                    "checked": detected["checked"],
                    "message": "Antigravity CLI command was not found.",
                    "resultPath": str(result_path),
                },
            },
        )
        raise ToolError(
            "Antigravity CLI command was not found. Install Antigravity CLI or set ANTIGRAVITY_COMMAND "
            "to the full executable path, then retry run_antigravity_handoff."
        )

    update_handoff(
        handoff.get("id"),
        {
            "status": "RUNNING",
            "lastRun": {
                "at": now_iso(),
                "commandLine": command_line,
                "repoPath": str(repo_path),
                "resultPath": str(result_path),
                "waitForResult": wait_for_result,
            },
        },
    )
    try:
        completed = subprocess.run(
            command_line,
            cwd=str(repo_path.resolve()),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_sec,
            env=antigravity_subprocess_env(resolved_command),
        )
    except subprocess.TimeoutExpired as exc:
        update_handoff(
            handoff.get("id"),
            {
                "status": "TIMED_OUT",
                "lastRun": {
                    "at": now_iso(),
                    "commandLine": command_line,
                    "repoPath": str(repo_path.resolve()),
                    "timeoutSec": timeout_sec,
                    "resultPath": str(result_path),
                    "stdout": (exc.stdout or "")[-4000:],
                    "stderr": (exc.stderr or "")[-4000:],
                },
            },
        )
        raise ToolError(f"Antigravity handoff timed out after {timeout_sec} seconds.")

    if completed.returncode == 0 and resolved_style == "ide_chat":
        status = "LAUNCHED"
    else:
        status = "COMPLETED" if completed.returncode == 0 else "FAILED"
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    stdout_empty = not stdout.strip()
    stderr_empty = not stderr.strip()
    run_record = {
        "at": now_iso(),
        "commandLine": command_line,
        "repoPath": str(repo_path.resolve()),
        "executionStyle": resolved_style,
        "completionCapture": resolved_style != "ide_chat",
        "waitForResult": wait_for_result,
        "resultPath": str(result_path),
        "exitCode": completed.returncode,
        "stdoutEmpty": stdout_empty,
        "stderrEmpty": stderr_empty,
        "stdoutTail": stdout[-4000:],
        "stderrTail": stderr[-4000:],
    }
    result_payload: dict[str, Any] | None = None
    if completed.returncode == 0 and wait_for_result:
        effective_result_timeout_sec = result_timeout_sec
        if resolved_style == "agy_print" and stdout_empty and not result_path.exists():
            effective_result_timeout_sec = min(result_timeout_sec, empty_stdout_result_grace_sec)
            run_record["emptyStdoutResultGraceSec"] = effective_result_timeout_sec
            run_record["diagnostic"] = (
                "agy --print exited 0 with empty stdout and no result file. agy print mode can stream "
                "planner/tool-call events without emitting a final printable response; use the result "
                "mailbox or report MCP as the completion signal."
            )
        result_payload = wait_for_result_file(result_path, effective_result_timeout_sec, poll_interval_sec)
        run_record["result"] = result_payload
        if result_payload["ready"]:
            status = "COMPLETED"
        elif resolved_style == "agy_print" and stdout_empty:
            status = "DEGRADED_NO_RESULT"
        else:
            status = "AWAITING_RESULT"

    updated = update_handoff(handoff.get("id"), {"status": status, "lastRun": run_record})
    response = {
        "handoff": updated or handoff,
        "status": status,
        "exitCode": completed.returncode,
        "executionStyle": resolved_style,
        "completionCapture": resolved_style != "ide_chat",
        "waitForResult": wait_for_result,
        "resultPath": str(result_path),
        "stdoutEmpty": stdout_empty,
        "stderrEmpty": stderr_empty,
        "stdoutTail": stdout[-4000:],
        "stderrTail": stderr[-4000:],
    }
    if result_payload is not None:
        response["result"] = result_payload
    return response


def tool_antigravity_get_result(args: dict[str, Any]) -> dict[str, Any]:
    result_path_arg = optional_string(args, "resultPath", 2000)
    handoff_ref = optional_string(args, "handoff", 2000)
    if not result_path_arg and not handoff_ref:
        raise ToolError("Provide either handoff or resultPath.")

    handoff: dict[str, Any] | None = None
    if handoff_ref:
        handoff = find_handoff_by_id_or_path(handoff_ref)
        last_run = handoff.get("lastRun", {})
        result_path_arg = result_path_arg or last_run.get("resultPath")
        if not result_path_arg:
            result_path = resolve_result_path(None, handoff)
        else:
            result_path = resolve_result_path(str(result_path_arg), handoff)
    else:
        result_path = resolve_result_path(result_path_arg, {"id": "external-result"})

    wait_timeout_sec = optional_int(args, "waitTimeoutSec", 0, 0, 14400)
    poll_interval_sec = optional_int(args, "pollIntervalSec", 5, 1, 120)
    if wait_timeout_sec > 0:
        result = wait_for_result_file(result_path, wait_timeout_sec, poll_interval_sec)
    else:
        ready, text = read_ready_result(result_path)
        result = {
            "ready": ready,
            "path": str(result_path),
            "content": text if ready else None,
            "contentTail": "" if ready else text[-4000:],
            "marker": ANTIGRAVITY_RESULT_MARKER,
        }

    status = "COMPLETED" if result["ready"] else "AWAITING_RESULT"
    if handoff and handoff.get("id"):
        update_handoff(handoff.get("id"), {"status": status, "lastResultCheck": {"at": now_iso(), "result": result}})
    return {"handoff": handoff, "status": status, "result": result}


def tool_submit_antigravity_result(args: dict[str, Any]) -> dict[str, Any]:
    # Compatibility result path for agents that can see the full main server.
    # The safer default for Antigravity is complete_dev_triangle_handoff in the
    # report-only server, because that exposes only the minimum return channel.
    handoff_ref = require_string(args, "handoff", 2000)
    status = optional_string(args, "status", 100) or "COMPLETED"
    recommendation = optional_string(args, "recommendation", 2000) or ""
    summary = require_string(args, "summary", 20000)
    commands_run = optional_string_list(args, "commandsRun")
    findings = optional_string_list(args, "findings")
    follow_ups = optional_string_list(args, "followUps")
    result_path_arg = optional_string(args, "resultPath", 2000)

    handoff = find_handoff_by_id_or_path(handoff_ref)
    result_path = resolve_result_path(result_path_arg, handoff)
    lines = [
        f"# Antigravity Result: {handoff.get('title') or handoff.get('id') or 'handoff'}",
        "",
        f"- handoffId: {handoff.get('id') or ''}",
        f"- submittedAt: {now_iso()}",
        f"- status: {status}",
        f"- recommendation: {recommendation}",
        "",
        "## Summary",
        summary,
        "",
    ]
    if commands_run:
        lines += ["## Commands Run", *[f"- `{item}`" for item in commands_run], ""]
    if findings:
        lines += ["## Findings", *[f"- {item}" for item in findings], ""]
    if follow_ups:
        lines += ["## Follow Ups", *[f"- {item}" for item in follow_ups], ""]
    lines += [ANTIGRAVITY_RESULT_MARKER, ""]
    result_path.write_text("\n".join(lines), encoding="utf-8")

    result = {"ready": True, "path": str(result_path), "content": "\n".join(lines), "marker": ANTIGRAVITY_RESULT_MARKER}
    updated = update_handoff(
        handoff.get("id"),
        {
            "status": status,
            "resultPath": str(result_path),
            "submittedResult": {
                "at": now_iso(),
                "status": status,
                "recommendation": recommendation,
                "summary": summary,
                "commandsRun": commands_run,
                "findings": findings,
                "followUps": follow_ups,
            },
        },
    )
    return {"handoff": updated or handoff, "status": status, "result": result}


def tool_mcp_health_check(args: dict[str, Any]) -> dict[str, Any]:
    include_jules = args.get("includeJules", False)
    if not isinstance(include_jules, bool):
        raise ToolError("Argument includeJules must be a boolean.")
    include_antigravity_print_smoke = args.get("includeAntigravityPrintSmoke", False)
    if not isinstance(include_antigravity_print_smoke, bool):
        raise ToolError("Argument includeAntigravityPrintSmoke must be a boolean.")
    antigravity_smoke_timeout_sec = optional_int(args, "antigravitySmokeTimeoutSec", 30, 5, 120)
    antigravity = resolve_antigravity_command(optional_string(args, "antigravityCommand", 2000))
    payload: dict[str, Any] = {
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION, "protocolVersion": PROTOCOL_VERSION},
        "python": sys.version.split()[0],
        "paths": {
            "root": str(ROOT),
            "home": str(DEV_TRIANGLE_HOME),
            "ledger": str(LEDGER_PATH),
            "handoffs": str(HANDOFF_DIR),
            "results": str(RESULT_DIR),
            "patches": str(PATCH_DIR),
        },
        "jules": {"apiKeyPresent": bool(os.environ.get("JULES_API_KEY", "").strip())},
        "antigravity": {
            "available": antigravity["available"],
            "command": antigravity["command"],
            "commandKind": antigravity_command_kind(antigravity["command"]),
            "checked": antigravity["checked"],
        },
        "ledger": {
            "jobCount": len(load_ledger().get("jobs", [])),
            "handoffCount": len(load_ledger().get("handoffs", [])),
        },
    }
    if include_jules:
        try:
            sources = http_json("GET", "/sources", params={"pageSize": 5}).get("sources", [])
            payload["jules"]["reachable"] = True
            payload["jules"]["sourceCount"] = len(sources)
            payload["jules"]["sources"] = [source.get("name") for source in sources]
        except ToolError as exc:
            payload["jules"]["reachable"] = False
            payload["jules"]["error"] = str(exc)
    if include_antigravity_print_smoke:
        payload["antigravity"]["printSmoke"] = run_antigravity_print_smoke(
            antigravity["command"],
            antigravity_smoke_timeout_sec,
        )
    return payload


def tool_job_list(args: dict[str, Any]) -> dict[str, Any]:
    ledger = load_ledger()
    provider = optional_string(args, "provider", 100)
    status = optional_string(args, "status", 100)
    limit = optional_int(args, "limit", 50, 1, 500)
    jobs = ledger.get("jobs", [])
    if provider:
        jobs = [job for job in jobs if job.get("provider") == provider]
    if status:
        jobs = [job for job in jobs if job.get("status") == status]
    return {"ledgerPath": str(LEDGER_PATH.resolve()), "jobs": jobs[-limit:], "handoffs": ledger.get("handoffs", [])[-limit:]}


def tool_job_get(args: dict[str, Any]) -> dict[str, Any]:
    job_id = require_string(args, "jobId", 200)
    ledger = load_ledger()
    for job in ledger.get("jobs", []):
        if job.get("id") == job_id:
            return {"job": job}
    for handoff in ledger.get("handoffs", []):
        if handoff.get("id") == job_id:
            return {"handoff": handoff}
    raise ToolError(f"No job or handoff found with id {job_id}.")


def tool_job_update(args: dict[str, Any]) -> dict[str, Any]:
    job_id = require_string(args, "jobId", 200)
    status = optional_string(args, "status", 100)
    notes = optional_string(args, "notes", 10000)
    ledger = load_ledger()
    for bucket in ("jobs", "handoffs"):
        for item in ledger.get(bucket, []):
            if item.get("id") == job_id:
                if status:
                    item["status"] = status
                if notes:
                    item.setdefault("notes", [])
                    item["notes"].append({"at": now_iso(), "text": notes})
                item["updatedAt"] = now_iso()
                save_ledger(ledger)
                return {bucket[:-1]: item}
    raise ToolError(f"No job or handoff found with id {job_id}.")


def schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


TOOLS = [
    # The MCP schema is intentionally explicit and conservative. Every tool has
    # a narrow input shape so clients can render safe UI and agents get fewer
    # opportunities to invent unsupported arguments.
    {
        "name": "jules_list_sources",
        "title": "List Jules Sources",
        "description": "List GitHub repositories already connected to Jules. Use before creating repository-backed Jules sessions.",
        "inputSchema": schema(
            {
                "pageSize": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
                "pageToken": {"type": "string"},
                "filter": {"type": "string"},
            }
        ),
    },
    {
        "name": "jules_list_sessions",
        "title": "List Jules Sessions",
        "description": "List recent Jules sessions for the authenticated user.",
        "inputSchema": schema(
            {
                "pageSize": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "pageToken": {"type": "string"},
            }
        ),
    },
    {
        "name": "jules_create_session",
        "title": "Create Jules Session",
        "description": "Create a Jules coding session. Defaults to requirePlanApproval=true so plans pause for review.",
        "inputSchema": schema(
            {
                "prompt": {"type": "string", "description": "Task for Jules to execute."},
                "title": {"type": "string"},
                "source": {"type": "string", "description": "Jules source name, github/owner/repo, or owner/repo."},
                "startingBranch": {"type": "string"},
                "requirePlanApproval": {"type": "boolean", "default": True},
                "automationMode": {"type": "string", "description": "Optional, e.g. AUTO_CREATE_PR."},
            },
            ["prompt"],
        ),
    },
    {
        "name": "prepare_jules_repo",
        "title": "Prepare Local Project For Jules",
        "description": (
            "Inspect or publish a local project as a GitHub repository Jules can use. "
            "Defaults to dry-run; publish=true requires confirmPublish=true and defaults to private visibility."
        ),
        "inputSchema": schema(
            {
                "repoPath": {"type": "string", "description": "Local project directory to prepare."},
                "publish": {"type": "boolean", "default": False},
                "confirmPublish": {"type": "boolean", "default": False},
                "repoName": {"type": "string", "description": "Optional GitHub repository name. Defaults to folder name."},
                "githubOwner": {"type": "string", "description": "Optional GitHub user or org. Defaults to gh authenticated user."},
                "visibility": {"type": "string", "description": "private, public, or internal. Defaults to private."},
                "confirmPublic": {"type": "boolean", "default": False},
                "remoteName": {"type": "string", "default": "origin"},
                "branch": {"type": "string", "description": "Branch to publish. Defaults to current branch or main."},
                "createRemote": {"type": "boolean", "default": True},
                "push": {"type": "boolean", "default": True},
                "commitChanges": {"type": "boolean", "default": False},
                "commitMessage": {"type": "string", "default": "Prepare project for Jules"},
                "checkJulesSource": {"type": "boolean", "default": False},
            },
            ["repoPath"],
        ),
    },
    {
        "name": "jules_get_session",
        "title": "Get Jules Session",
        "description": "Get a Jules session and update the local job ledger.",
        "inputSchema": schema({"session": {"type": "string", "description": "Session id or sessions/{id}."}}, ["session"]),
    },
    {
        "name": "jules_list_activities",
        "title": "List Jules Activities",
        "description": "List Jules session activities, including plans, progress, messages, and artifacts.",
        "inputSchema": schema(
            {
                "session": {"type": "string"},
                "pageSize": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                "pageToken": {"type": "string"},
                "createTime": {"type": "string", "description": "Optional timestamp filter supported by Jules."},
            },
            ["session"],
        ),
    },
    {
        "name": "jules_send_message",
        "title": "Send Message To Jules",
        "description": "Send feedback or additional instructions to an active Jules session.",
        "inputSchema": schema({"session": {"type": "string"}, "prompt": {"type": "string"}}, ["session", "prompt"]),
    },
    {
        "name": "jules_approve_plan",
        "title": "Approve Jules Plan",
        "description": "Approve a pending Jules plan for sessions created with requirePlanApproval=true.",
        "inputSchema": schema({"session": {"type": "string"}}, ["session"]),
    },
    {
        "name": "jules_get_outputs",
        "title": "Get Jules Outputs",
        "description": "Get completed Jules outputs and optionally include patch artifacts from activities.",
        "inputSchema": schema(
            {"session": {"type": "string"}, "includePatches": {"type": "boolean", "default": False}},
            ["session"],
        ),
    },
    {
        "name": "jules_save_latest_patch",
        "title": "Save Latest Jules Patch",
        "description": "Find the latest git patch artifact in a Jules session and save it under the local patch directory.",
        "inputSchema": schema({"session": {"type": "string"}, "fileName": {"type": "string"}}, ["session"]),
    },
    {
        "name": "create_antigravity_handoff",
        "title": "Create Antigravity Handoff",
        "description": "Create a local handoff markdown file for Antigravity to run a local verification or repair loop.",
        "inputSchema": schema(
            {
                "title": {"type": "string"},
                "objective": {"type": "string"},
                "repoPath": {"type": "string"},
                "context": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
                "suggestedCommands": {"type": "array", "items": {"type": "string"}},
                "acceptanceCriteria": {"type": "string"},
                "sourceJobId": {"type": "string"},
            },
            ["objective"],
        ),
    },
    {
        "name": "antigravity_detect_cli",
        "title": "Detect Antigravity CLI",
        "description": "Detect whether an Antigravity CLI command is available for non-interactive handoff execution.",
        "inputSchema": schema(
            {
                "command": {"type": "string", "description": "Optional executable path or command name."},
                "smokePrint": {"type": "boolean", "default": False},
                "smokeTimeoutSec": {"type": "integer", "minimum": 5, "maximum": 120, "default": 30},
            }
        ),
    },
    {
        "name": "run_antigravity_handoff",
        "title": "Run Antigravity Handoff",
        "description": "Run a prepared handoff through Antigravity CLI non-interactive mode. Use dryRun to verify command construction without launching Antigravity.",
        "inputSchema": schema(
            {
                "handoff": {"type": "string", "description": "Handoff id or path."},
                "repoPath": {"type": "string"},
                "command": {"type": "string", "description": "Optional Antigravity executable path or command name."},
                "promptArg": {"type": "string", "default": "-p"},
                "mode": {"type": "string", "description": "Antigravity IDE chat mode: ask, edit, or agent.", "default": "agent"},
                "windowMode": {"type": "string", "description": "Antigravity IDE window mode: default, new, or reuse.", "default": "new"},
                "executionStyle": {
                    "type": "string",
                    "description": "auto, agy_print, ide_chat, or prompt_arg.",
                    "default": "auto",
                },
                "timeoutSec": {"type": "integer", "minimum": 30, "maximum": 14400, "default": 1800},
                "waitForResult": {"type": "boolean", "default": False},
                "resultPath": {"type": "string", "description": "Optional result report path under the configured result directory."},
                "resultTimeoutSec": {"type": "integer", "minimum": 10, "maximum": 14400, "default": 1800},
                "emptyStdoutResultGraceSec": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "default": 15,
                    "description": "Short grace wait when agy --print exits 0 with empty stdout and no result file.",
                },
                "pollIntervalSec": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
                "dryRun": {"type": "boolean", "default": False},
            },
            ["handoff"],
        ),
    },
    {
        "name": "antigravity_get_result",
        "title": "Get Antigravity Result",
        "description": "Read or wait for an Antigravity handoff result file written through the closed-loop mailbox contract.",
        "inputSchema": schema(
            {
                "handoff": {"type": "string", "description": "Handoff id or path."},
                "resultPath": {"type": "string"},
                "waitTimeoutSec": {"type": "integer", "minimum": 0, "maximum": 14400, "default": 0},
                "pollIntervalSec": {"type": "integer", "minimum": 1, "maximum": 120, "default": 5},
            }
        ),
    },
    {
        "name": "submit_antigravity_result",
        "title": "Submit Antigravity Result",
        "description": "Submit a completed Antigravity verification result back to the MCP ledger and result mailbox. Intended for Antigravity agents that can call this MCP server.",
        "inputSchema": schema(
            {
                "handoff": {"type": "string", "description": "Handoff id or path."},
                "status": {"type": "string", "default": "COMPLETED"},
                "recommendation": {"type": "string"},
                "summary": {"type": "string"},
                "commandsRun": {"type": "array", "items": {"type": "string"}},
                "findings": {"type": "array", "items": {"type": "string"}},
                "followUps": {"type": "array", "items": {"type": "string"}},
                "resultPath": {"type": "string"},
            },
            ["handoff", "summary"],
        ),
    },
    {
        "name": "mcp_health_check",
        "title": "MCP Health Check",
        "description": "Check local MCP server paths, ledger counts, Jules key presence/reachability, and Antigravity CLI detection.",
        "inputSchema": schema(
            {
                "includeJules": {"type": "boolean", "default": False},
                "antigravityCommand": {"type": "string"},
                "includeAntigravityPrintSmoke": {"type": "boolean", "default": False},
                "antigravitySmokeTimeoutSec": {"type": "integer", "minimum": 5, "maximum": 120, "default": 30},
            }
        ),
    },
    {
        "name": "job_list",
        "title": "List Triangle Jobs",
        "description": "List local dev-triangle jobs and Antigravity handoffs from the ledger.",
        "inputSchema": schema(
            {
                "provider": {"type": "string"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
            }
        ),
    },
    {
        "name": "job_get",
        "title": "Get Triangle Job",
        "description": "Get one local job or handoff by id.",
        "inputSchema": schema({"jobId": {"type": "string"}}, ["jobId"]),
    },
    {
        "name": "job_update",
        "title": "Update Triangle Job",
        "description": "Update local job or handoff status and append notes.",
        "inputSchema": schema(
            {"jobId": {"type": "string"}, "status": {"type": "string"}, "notes": {"type": "string"}},
            ["jobId"],
        ),
    },
]


HANDLERS = {
    "jules_list_sources": tool_jules_list_sources,
    "jules_list_sessions": tool_jules_list_sessions,
    "jules_create_session": tool_jules_create_session,
    "prepare_jules_repo": tool_prepare_jules_repo,
    "jules_get_session": tool_jules_get_session,
    "jules_list_activities": tool_jules_list_activities,
    "jules_send_message": tool_jules_send_message,
    "jules_approve_plan": tool_jules_approve_plan,
    "jules_get_outputs": tool_jules_get_outputs,
    "jules_save_latest_patch": tool_jules_save_latest_patch,
    "create_antigravity_handoff": tool_create_antigravity_handoff,
    "antigravity_detect_cli": tool_antigravity_detect_cli,
    "run_antigravity_handoff": tool_run_antigravity_handoff,
    "antigravity_get_result": tool_antigravity_get_result,
    "submit_antigravity_result": tool_submit_antigravity_result,
    "mcp_health_check": tool_mcp_health_check,
    "job_list": tool_job_list,
    "job_get": tool_job_get,
    "job_update": tool_job_update,
}


def tool_result(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": compact_text(data)}],
        "structuredContent": data,
        "isError": False,
    }


def tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": {"error": message},
        "isError": True,
    }


def jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    # Minimal JSON-RPC dispatcher for stdio MCP clients. Keeping this local and
    # dependency-free makes the server easy to install in Codex, Claude Desktop,
    # Gemini CLI, or any other MCP-capable client.
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if request_id is None and method in {"notifications/initialized", "notifications/cancelled"}:
        return None

    if method == "initialize":
        return jsonrpc_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Use this server as a thin dev workflow control plane. "
                    "Send repeatable cloud coding work to Jules, keep plan approval on unless the user says otherwise, "
                    "and create Antigravity handoffs for local verification loops. "
                    "Do not treat this server as a shell executor. "
                    "When you are Antigravity completing a handoff, submit your final report with submit_antigravity_result; "
                    "if that tool is unavailable, write the report to the provided RESULT_PATH and include DEV_TRIANGLE_RESULT_READY."
                ),
            },
        )

    if method == "ping":
        return jsonrpc_result(request_id, {})

    if method == "tools/list":
        return jsonrpc_result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str) or name not in HANDLERS:
            return jsonrpc_result(request_id, tool_error(f"Unknown tool: {name}"))
        if not isinstance(args, dict):
            return jsonrpc_result(request_id, tool_error("Tool arguments must be an object."))
        try:
            ensure_dirs()
            data = HANDLERS[name](args)
            return jsonrpc_result(request_id, tool_result(data))
        except ToolError as exc:
            return jsonrpc_result(request_id, tool_error(str(exc)))
        except Exception as exc:  # Defensive: keep MCP connection alive.
            return jsonrpc_result(request_id, tool_error(f"Internal server error: {type(exc).__name__}: {exc}"))

    if method == "resources/list":
        return jsonrpc_result(request_id, {"resources": []})

    if method == "prompts/list":
        return jsonrpc_result(request_id, {"prompts": []})

    if method == "logging/setLevel":
        return jsonrpc_result(request_id, {})

    return jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def write_response(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def configure_stdio() -> None:
    # MCP stdio payloads are JSON and should be UTF-8. On Windows, Python can
    # otherwise inherit a legacy codepage for piped stdout, which makes clients
    # that correctly read UTF-8 fail on non-ASCII diagnostic text.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    configure_stdio()
    ensure_dirs()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            write_response(jsonrpc_error(None, -32700, "Parse error"))
            continue

        messages = payload if isinstance(payload, list) else [payload]
        responses = []
        for message in messages:
            if not isinstance(message, dict):
                responses.append(jsonrpc_error(None, -32600, "Invalid request"))
                continue
            response = handle_message(message)
            if response is not None:
                responses.append(response)
        if not responses:
            continue
        if isinstance(payload, list):
            write_response(responses)
        else:
            write_response(responses[0])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
