# Dev Triangle MCP source maintenance contract
# 上下游: 上游是 server.py 的 tool_profile_set_role（寫入前比對模型 ID）；下游由各家 adapter 註冊自己的列表函式；本檔自己不發任何網路請求
# 檔案路徑: dev-triangle-mcp/providers/models.py
# 產生時間: 2026-08-19 14:05 +08:00
# 版本: v1.0
# 功能說明: 回答「這個 provider 有沒有辦法列出它支援哪些模型，如果有，這個模型 ID 存不存在」。用來擋住模型自己編出來的模型 ID
# 模組定位: INV-14 的判斷入口與註冊表。它「是」一層薄薄的間接層；它「不是」HTTP 傳輸層（那是 providers/http.py），也「不是」模型清單的快取或真相來源
# 主要責任:
#   1. register_lister(dialect, fn) —— adapter 啟動時把自己的列表能力登記進來
#   2. list_models(binding) —— 回傳模型 ID 清單，或 None 表示「這家沒辦法列」
#   3. closest_matches(candidate, known) —— 對不到時給使用者最接近的幾個選項
# 維護提醒:
#   - list_models 回 None 與回 [] 意思完全不同。None 是「無法查證」，[] 是「查證過，一個都沒有」。不得把 None 當成空清單處理，那會讓所有寫入都被拒絕
#   - 「無法查證」的正確處置是標 verified: false，不是把它排除在分母外。排除分母就是把 S4.10 的量尺關掉
#   - 不得在此檔快取結果。使用者剛在供應商後台開通一個新模型，這裡就應該立刻看得到
# 驗證方式:
#   - python -m pytest -q tests\test_nl_config.py
# ------------------------------------------------------------

from __future__ import annotations

import difflib
from typing import Any, Callable


# dialect -> callable(binding) -> list[str] | None
ModelLister = Callable[[Any], "list[str] | None"]

_LISTERS: dict[str, ModelLister] = {}


def register_lister(dialect: str, lister: ModelLister) -> None:
    _LISTERS[dialect] = lister


def clear_listers() -> None:
    """Only for tests. Production code registers at import time and leaves it."""
    _LISTERS.clear()


def has_lister(dialect: str) -> bool:
    return dialect in _LISTERS


def list_models(binding: Any) -> list[str] | None:
    """Return the provider's model ids, or None when this provider cannot list them.

    None is not an error and not an empty list. It means "unverifiable", which
    is a legitimate state that gets recorded as verified: false rather than
    quietly dropped (INV-14).
    """
    dialect = getattr(binding, "dialect", "") or ""
    lister = _LISTERS.get(dialect)
    if lister is None:
        return None
    return lister(binding)


def closest_matches(candidate: str, known: list[str], limit: int = 5) -> list[str]:
    if not known:
        return []
    close = difflib.get_close_matches(candidate, known, n=limit, cutoff=0.4)
    if close:
        return close
    return sorted(known)[:limit]
