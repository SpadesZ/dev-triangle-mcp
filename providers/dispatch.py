# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 providers/context_broker.py 與 providers/architect.py；依 RoleBinding.kind 把工作分給 providers/http.py（api）或 providers/cli_agent.py（cli）；不自己發任何請求、不做遮罩
# 檔案路徑: dev-triangle-mcp/providers/dispatch.py
# 產生時間: 2026-08-19 18:25 +08:00
# 版本: v1.0
# 功能說明: 讓「這個角色綁的是計費 API 還是本機 CLI」變成 adapter 不必知道的事。兩棒的程式碼只呼叫 send()，換綁定不必改任何一行 adapter
# 模組定位: 路由層。它「是」kind → 傳輸層的分派與統一回傳形狀；它「不是」傳輸層本身、「不是」遮罩層（呼叫端要先過 outbound）、也「不是」重試或降級層——它只重問一次格式，不換模型
# 主要責任:
#   1. send(binding, system, user) —— 依 kind 路由，回傳 {targetBaseUrl, targetModel, text, usage}
#   2. send_expecting_json(binding, system, user, parse) —— 解析失敗時重問一次「只回 JSON」
#   3. destination_of(binding) —— 在還沒送出之前就能講出去向，給健康檢查與拒絕路徑用
# 維護提醒:
#   - 不得在此加「這家不行就換那家」的備援。擁有者已裁決用 profile 切換而不是自動降級；自動降級會讓使用者以為用的是 A 其實是 B，而帳面全綠（見 docs/NOTES.md NOTE-011）
#   - 重問只重問一次。第二次還是解析不到就報錯，不得無限重問——那是一個沒有煞車的迴圈，理由與 INV-08 同源
#   - 回傳形狀兩條路徑必須完全一致，包含 usage 這個鍵。上層用 usage 有沒有內容判斷要不要記 token（NOTE-010）
# 驗證方式:
#   - python -m pytest -q tests\test_cli_agent.py
# ------------------------------------------------------------

from __future__ import annotations

from typing import Any, Callable

from providers import cli_agent, http
from providers.profiles import RoleBinding


JSON_RETRY_INSTRUCTION = (
    "Your previous reply could not be parsed as JSON. Reply again with ONLY the JSON object. "
    "No prose before or after it, no markdown code fences, no explanation."
)


class DispatchError(Exception):
    pass


def destination_of(binding: RoleBinding) -> dict[str, str]:
    """What the payload is about to be sent to, before sending it.

    targetModel is reported exactly as configured, including empty. An empty
    model on a cli role is the truth - that CLI picks its own - and inventing a
    placeholder here would both trip the S4.9 metric and put a string in an
    audit field that no one chose.
    """
    if binding.kind == "cli":
        try:
            target = cli_agent.resolve_executable(binding)
        except cli_agent.CliAgentError:
            target = binding.command
        return {
            "targetBaseUrl": target,
            "targetModel": binding.model,
            "targetModelSource": "profile" if binding.model else "cli-default",
        }
    return {
        "targetBaseUrl": binding.base_url or http.default_base_url(binding.dialect),
        "targetModel": binding.model,
        "targetModelSource": "profile",
    }


def send(binding: RoleBinding, system: str, user: str) -> dict[str, Any]:
    if binding.kind == "cli":
        try:
            return cli_agent.run_agent(binding, system, user)
        except cli_agent.CliAgentError as exc:
            raise DispatchError(str(exc)) from exc
    if binding.kind == "api":
        try:
            return http.chat(binding, system, user)
        except http.TransportError as exc:
            raise DispatchError(str(exc)) from exc
    raise DispatchError(
        f"Role {binding.slot!r} has kind {binding.kind!r}, which cannot be dispatched to. "
        "Only 'api' and 'cli' roles take work this way."
    )


def send_expecting_json(
    binding: RoleBinding,
    system: str,
    user: str,
    parse: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Send, parse, and on a parse failure re-ask exactly once.

    Returns (parsed, response). The re-ask exists because a CLI agent is far
    more likely than an API to wrap its answer in conversation; it is capped at
    one because a parse-retry loop with no ceiling is the same unbraked loop
    INV-08 forbids elsewhere.
    """
    response = send(binding, system, user)
    try:
        return parse(response["text"]), response
    except Exception as first_error:  # noqa: BLE001 - adapters raise their own types
        retry_system = f"{system}\n\n{JSON_RETRY_INSTRUCTION}" if system else JSON_RETRY_INSTRUCTION
        retry = send(binding, retry_system, user)
        try:
            parsed = parse(retry["text"])
        except Exception as second_error:  # noqa: BLE001
            raise DispatchError(
                f"Role {binding.slot!r} did not return usable JSON on either attempt. "
                f"First: {first_error}. After asking for JSON only: {second_error}."
            ) from second_error
        retry["retriedForJson"] = True
        return parsed, retry
