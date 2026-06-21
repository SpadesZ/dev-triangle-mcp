"""Report-only MCP server for worker/verifier agents.

This server is intentionally tiny. Antigravity and future worker agents should
use this surface to report completion without receiving the full Dev Triangle
control plane.

Human orientation:
  The main server (server.py) creates handoffs and launches workers.
  This server only accepts final reports and writes them into the shared local
  ledger/result mailbox.

Why this exists:
  A worker that only needs to say "I finished, here are the results" should not
  see Jules tools, job mutation tools, or other orchestration features.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERVER_NAME = "dev-triangle-report"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"

ROOT = Path(__file__).resolve().parent
DEV_TRIANGLE_HOME = Path(
    os.environ.get("DEV_TRIANGLE_HOME", str(ROOT / ".dev-triangle"))
).expanduser()
LEDGER_PATH = DEV_TRIANGLE_HOME / "jobs.json"
HANDOFF_DIR = Path(
    os.environ.get("ANTIGRAVITY_HANDOFF_DIR", str(DEV_TRIANGLE_HOME / "antigravity-handoffs"))
).expanduser()
RESULT_DIR = DEV_TRIANGLE_HOME / "antigravity-results"
ANTIGRAVITY_RESULT_MARKER = "DEV_TRIANGLE_RESULT_READY"


class ToolError(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    DEV_TRIANGLE_HOME.mkdir(parents=True, exist_ok=True)
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def compact_text(value: Any, limit: int = 6000) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... truncated ..."


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    # NOTE: Use a temp file followed by replace so the shared ledger is not left
    # as truncated JSON if this process is interrupted mid-write.
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


def sanitize_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return value or fallback


def require_string(args: dict[str, Any], name: str, max_len: int = 20000) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolError(f"Missing required string argument: {name}.")
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


def optional_string_list(args: dict[str, Any], name: str) -> list[str]:
    value = args.get(name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolError(f"Argument {name} must be an array of strings.")
    return [item.strip() for item in value if item.strip()]


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve()).lower()


def find_handoff_by_id_or_path(handoff_ref: str) -> dict[str, Any]:
    # Workers may receive either the stable handoff id or the markdown path.
    # Supporting both makes prompts less brittle while still requiring a ledger
    # entry before a result can be accepted.
    ledger = load_ledger()
    handoffs = ledger.get("handoffs", [])
    for handoff in handoffs:
        if handoff.get("id") == handoff_ref:
            return handoff

    ref_path: str | None = None
    try:
        candidate = Path(handoff_ref).expanduser()
        if not candidate.is_absolute():
            candidate = (ROOT / candidate).resolve()
        ref_path = normalize_path(str(candidate))
    except OSError:
        ref_path = None

    if ref_path:
        for handoff in handoffs:
            path_value = handoff.get("path") or handoff.get("handoffPath")
            if isinstance(path_value, str) and normalize_path(path_value) == ref_path:
                return handoff

    raise ToolError(f"Handoff not found: {handoff_ref}")


def resolve_result_path(value: str | None, handoff: dict[str, Any]) -> Path:
    # Result paths are restricted to known handoff/result directories. This
    # prevents a worker from using the reporting tool to write arbitrary files.
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = RESULT_DIR / path
    elif isinstance(handoff.get("resultPath"), str) and handoff["resultPath"].strip():
        path = Path(handoff["resultPath"]).expanduser()
    else:
        handoff_id = handoff.get("id") or sanitize_filename(str(handoff.get("title", "handoff")), "handoff")
        path = RESULT_DIR / f"{sanitize_filename(str(handoff_id), 'handoff')}-result.md"

    path = path.resolve()
    allowed_roots = [RESULT_DIR.resolve(), HANDOFF_DIR.resolve()]
    if not any(str(path).lower().startswith(str(root).lower()) for root in allowed_roots):
        raise ToolError(f"Result path must be inside {RESULT_DIR} or {HANDOFF_DIR}: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def update_handoff(handoff_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ledger = load_ledger()
    for handoff in ledger.get("handoffs", []):
        if handoff.get("id") == handoff_id:
            handoff.update(updates)
            save_ledger(ledger)
            return handoff
    raise ToolError(f"Handoff not found: {handoff_id}")


def tool_dev_triangle_report_health(args: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    ledger = load_ledger()
    return {
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION, "protocolVersion": PROTOCOL_VERSION},
        "paths": {
            "home": str(DEV_TRIANGLE_HOME),
            "ledger": str(LEDGER_PATH),
            "handoffs": str(HANDOFF_DIR),
            "results": str(RESULT_DIR),
        },
        "handoffCount": len(ledger.get("handoffs", [])),
        "resultMarker": ANTIGRAVITY_RESULT_MARKER,
    }


def tool_complete_dev_triangle_handoff(args: dict[str, Any]) -> dict[str, Any]:
    # This is the preferred closed-loop return path. It writes both the human
    # readable markdown report and the machine-readable ledger update.
    ensure_dirs()
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
    submitted_at = now_iso()
    lines = [
        f"# Antigravity Result: {handoff.get('title') or handoff.get('id') or 'handoff'}",
        "",
        f"- handoffId: {handoff.get('id') or ''}",
        f"- submittedAt: {submitted_at}",
        f"- submittedBy: {SERVER_NAME}",
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
    content = "\n".join(lines)
    result_path.write_text(content, encoding="utf-8")

    updated = update_handoff(
        str(handoff.get("id")),
        {
            "status": status,
            "resultPath": str(result_path),
            "submittedResult": {
                "at": submitted_at,
                "via": SERVER_NAME,
                "status": status,
                "recommendation": recommendation,
                "summary": summary,
                "commandsRun": commands_run,
                "findings": findings,
                "followUps": follow_ups,
            },
        },
    )
    return {
        "handoff": updated,
        "status": status,
        "result": {"ready": True, "path": str(result_path), "content": content, "marker": ANTIGRAVITY_RESULT_MARKER},
    }


TOOLS = [
    # Keep this list deliberately small. The report server is meant to be safe
    # to expose to worker agents that should not orchestrate other tools.
    {
        "name": "dev_triangle_report_health",
        "description": "Check the tiny report-only MCP server used by Antigravity CLI to submit handoff results.",
        "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "complete_dev_triangle_handoff",
        "description": (
            "Submit the final Antigravity handoff report back to Codex. "
            "Use this as the only completion tool after finishing the requested verification."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "handoff": {"type": "string", "description": "Handoff id or handoff markdown path."},
                "status": {"type": "string", "default": "COMPLETED"},
                "recommendation": {"type": "string"},
                "summary": {"type": "string"},
                "commandsRun": {"type": "array", "items": {"type": "string"}},
                "findings": {"type": "array", "items": {"type": "string"}},
                "followUps": {"type": "array", "items": {"type": "string"}},
                "resultPath": {"type": "string"},
            },
            "required": ["handoff", "summary"],
            "additionalProperties": False,
        },
    },
]

HANDLERS = {
    "dev_triangle_report_health": tool_dev_triangle_report_health,
    "complete_dev_triangle_handoff": tool_complete_dev_triangle_handoff,
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
    # Same dependency-free stdio JSON-RPC shape as the main server, but with only
    # report submission tools registered.
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
                    "This is a report-only MCP server for Antigravity CLI. "
                    "After completing a dev-triangle handoff, call complete_dev_triangle_handoff exactly once. "
                    "Do not use this server for shell execution or task delegation."
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
            data = HANDLERS[name](args)
            return jsonrpc_result(request_id, tool_result(data))
        except ToolError as exc:
            return jsonrpc_result(request_id, tool_error(str(exc)))
        except Exception as exc:
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
    # Keep stdio MCP JSON consistently UTF-8 across Windows shells and CI.
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    configure_stdio()
    ensure_dirs()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            response = handle_message(message)
            if response is not None:
                write_response(response)
        except Exception as exc:
            write_response(jsonrpc_error(None, -32603, f"Internal error: {type(exc).__name__}: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
