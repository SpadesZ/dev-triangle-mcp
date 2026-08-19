# Dev Triangle MCP source maintenance contract
# 上下游: 由 pytest 收集執行；import server 的 build_antigravity_command_line 與 configured_antigravity_agy_model；不寫任何檔案、不啟動任何子行程
# 檔案路徑: dev-triangle-mcp/tests/test_antigravity_command_line.py
# 產生時間: 2026-08-19 10:52 +08:00
# 版本: v1.0
# 功能說明: 釘住 agy CLI 指令列的兩個組裝規則——prompt 只能傳一次，以及被列為 legacy unsafe 的模型值必須被丟掉而不是照傳。這兩件事改壞了都不會拋例外，只會讓 agy 收到錯的輸入
# 模組定位: NOTE-001 與 NOTE-002 的突變驗證載體。它「是」純函式層級的單元測試；它「不是」端對端煙霧測試(那是 tests/protocol_smoke.py，跑真的 MCP stdio 行程)
# 主要責任:
#   1. test_agy_print_passes_prompt_once —— 守 NOTE-002
#   2. test_legacy_unsafe_model_is_ignored —— 守 NOTE-001 的拒絕分支
#   3. test_user_chosen_model_is_passed_through —— 守 NOTE-001 的放行分支，避免測試被「乾脆不傳 --model」矇混過去
# 維護提醒:
#   - 不得只留第 2 支而刪掉第 3 支。只測拒絕不測放行的話，把整個 --model 參數拿掉也會全綠(docs/SAI.md I0.3「斷言要指名分支」)
#   - 測試用的模型字串不得寫成真實模型版本名，否則 S4.8 provider_lock_hits 會掃到(唯一的例外是 NOTE-001 那個拒絕清單本身)
# 驗證方式:
#   - python -m pytest -q tests\test_antigravity_command_line.py
# ------------------------------------------------------------

from __future__ import annotations

import server


PROMPT = "dev-triangle-unit-test-prompt-marker"
FAKE_MODEL = "test-only-model-id"


def build(execution_style: str = "agy_print") -> tuple[list[str], str]:
    return server.build_antigravity_command_line(
        command="agy",
        prompt=PROMPT,
        prompt_arg="-p",
        mode="agent",
        window_mode="new",
        execution_style=execution_style,
    )


def test_agy_print_passes_prompt_once() -> None:
    # NOTE(NOTE-002): prompt goes in through --print and nowhere else.
    command_line, style = build()
    assert style == "agy_print"
    assert command_line.count(PROMPT) == 1
    assert command_line[command_line.index("--print") + 1] == PROMPT


def test_legacy_unsafe_model_is_ignored(monkeypatch) -> None:
    # NOTE(NOTE-001): the deny list must drop the value, not forward it.
    legacy = next(iter(server.ANTIGRAVITY_LEGACY_UNSAFE_MODELS))
    monkeypatch.setenv("ANTIGRAVITY_AGY_MODEL", legacy)

    model, note = server.configured_antigravity_agy_model()
    assert model == ""
    assert note is not None and legacy in note

    command_line, _ = build()
    assert "--model" not in command_line
    assert legacy not in command_line


def test_user_chosen_model_is_passed_through(monkeypatch) -> None:
    # The other branch of NOTE-001: anything the user picked must survive.
    monkeypatch.setenv("ANTIGRAVITY_AGY_MODEL", FAKE_MODEL)

    model, note = server.configured_antigravity_agy_model()
    assert model == FAKE_MODEL
    assert note is None

    command_line, _ = build()
    assert command_line[command_line.index("--model") + 1] == FAKE_MODEL


def test_ide_chat_still_appends_prompt_positionally() -> None:
    # NOTE-002 is scoped to agy_print only. If someone "fixes" ide_chat by
    # removing its trailing append, the IDE route silently loses the prompt.
    command_line, style = build(execution_style="ide_chat")
    assert style == "ide_chat"
    assert command_line[-1] == PROMPT
