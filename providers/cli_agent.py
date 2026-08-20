# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 providers/dispatch.py（依 binding.kind 路由過來）；讀 RoleBinding 的 command/args/promptArg 組指令列，經 server.run_native 啟動子行程；送出去的 prompt 必須已經先過 providers/redaction.py
# 檔案路徑: dev-triangle-mcp/providers/cli_agent.py
# 產生時間: 2026-08-19 18:20 +08:00
# 版本: v1.0
# 功能說明: 把一段 prompt 交給本機的某支 agent CLI（claude / codex / gemini / agy 之類）執行，再把它印出來的東西當成回應收回來。讓「用訂閱制的 CLI」跟「用計費的 API」在上層看起來一樣
# 模組定位: 通用 CLI agent 傳輸層。它「是」指令列組裝與 stdout 收集；它「不是」受限驗證執行器（那支只跑目標 repo 自宣告的指令，且呼叫端不得傳指令字串——本檔剛好相反，指令由使用者在 profile 裡指定），也「不是」遮罩層
# 主要責任:
#   1. build_command(binding, prompt) —— 逐字組出 [command, *args, promptArg]，prompt 只在 promptVia 為 arg 時才進指令列
#   2. run_agent(binding, system, user, timeout) —— 執行並回傳與 providers/http.chat 相同形狀的結果
#   3. resolve_executable(binding) —— 用 shutil.which 解析，找不到就明講找不到哪一支
#   4. Windows argv 超過 CreateProcess 上限時先拒絕，避免把長度錯誤誤報成找不到執行檔
# 維護提醒:
#   - 不得為任何廠商內建旗標。args 是使用者逐字給的清單，本檔照抄不加工；一旦開始猜「claude 要用 --model、codex 要用 -m」，下一次那些 CLI 改版就會壞在這裡而沒人知道
#   - 預設用 stdin 送 prompt，不得改成預設走命令列引數，見 docs/NOTES.md NOTE-013
#   - 不得把 prompt 用 shell 字串拼接後丟給 shell。一律 list 形式、shell=False，理由與 INV-01 同源
#   - usage 一律回空 dict。CLI 不回報 token 數，捏一個數字出來比沒有更糟，見 docs/NOTES.md NOTE-010
#   - 本檔不做遮罩。呼叫端必須先過 providers/outbound.py，理由與 providers/http.py 相同
# 驗證方式:
#   - python -m pytest -q tests\test_cli_agent.py
# ------------------------------------------------------------

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from providers.profiles import RoleBinding


DEFAULT_TIMEOUT_SEC = 900
IS_WINDOWS = os.name == "nt"
WINDOWS_COMMAND_LINE_LIMIT = 32767


class CliAgentError(Exception):
    pass


def resolve_executable(binding: RoleBinding) -> str:
    command = (binding.command or "").strip()
    if not command:
        raise CliAgentError(
            f"Role {binding.slot!r} has kind 'cli' but no command. Set roles.{binding.slot}.command "
            "to the executable you want to hand the work to."
        )
    candidate = Path(command).expanduser()
    if candidate.exists():
        return str(candidate.resolve())
    found = shutil.which(command)
    if found:
        return found
    raise CliAgentError(
        f"Role {binding.slot!r} points at {command!r}, which is not on PATH and does not exist as a "
        "file. Check the command, or give the full path."
    )


def build_command(binding: RoleBinding, prompt: str | None = None) -> list[str]:
    """Assemble the command line verbatim from what the user configured.

    Shape is [command, *args, promptArg] plus the prompt only when this binding
    sends it as an argument. Nothing vendor-specific is added: a CLI that needs
    a model flag gets it because the user put it in args, not because this file
    knows which flag that CLI uses.
    """
    executable = resolve_executable(binding)
    line = [executable, *binding.args]
    if binding.prompt_arg:
        line.append(binding.prompt_arg)
    if binding.prompt_via == "arg" and prompt is not None:
        line.append(prompt)
    command_line_length = len(subprocess.list2cmdline(line))
    if IS_WINDOWS and command_line_length >= WINDOWS_COMMAND_LINE_LIMIT:
        raise CliAgentError(
            f"Role {binding.slot!r} cannot pass this prompt as an argument: the Windows command line "
            f"would be {command_line_length} characters (limit "
            f"{WINDOWS_COMMAND_LINE_LIMIT - 1}). Set promptVia to 'stdin' if this CLI supports it, "
            "or reduce the source input."
        )
    return line


def run_agent(
    binding: RoleBinding,
    system: str,
    user: str,
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> dict[str, Any]:
    """Hand one prompt to a CLI agent and return the same shape as http.chat.

    A CLI takes a single prompt, so the system instruction is folded into the
    top of the message rather than sent on a separate channel.
    """
    # Imported here rather than at module scope: server imports providers, so a
    # top-level import would be circular.
    from server import ToolError, run_native

    prompt = f"{system}\n\n---\n\n{user}" if system else user
    command_line = build_command(binding, prompt)
    # NOTE(NOTE-013): stdin is the default channel because these prompts are
    # long and multi-line, and the command line is neither.
    stdin_text = prompt if binding.prompt_via == "stdin" else None

    try:
        result = run_native(command_line, timeout=timeout, allow_failure=True, input_text=stdin_text)
    except ToolError as exc:
        raise CliAgentError(f"Role {binding.slot!r} CLI failed to run: {exc}") from exc

    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    if result.get("exitCode") != 0:
        raise CliAgentError(
            f"Role {binding.slot!r} CLI exited {result.get('exitCode')}. stderr tail: {stderr[-800:]}"
        )
    if not stdout:
        raise CliAgentError(
            f"Role {binding.slot!r} CLI exited 0 but printed nothing. Some agent CLIs need an explicit "
            "print/non-interactive flag; check roles."
            f"{binding.slot}.promptArg and args. stderr tail: {stderr[-800:]}"
        )

    return {
        # INV-15(c): for a CLI the destination is the binary that ran, and the
        # user needs to see that as much as they would a URL.
        "targetBaseUrl": command_line[0],
        # NOTE(NOTE-009): reported as configured, including empty. An empty
        # model here means the CLI chose; saying so beats inventing a label.
        "targetModel": binding.model,
        "targetModelSource": "profile" if binding.model else "cli-default",
        "text": stdout,
        # NOTE(NOTE-010): empty on purpose. A CLI does not report token counts,
        # and a fabricated zero reads as "this was free".
        "usage": {},
    }
