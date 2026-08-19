# NOTES — 產品與安全決策記錄

> 檔案路徑：`docs/NOTES.md`
> 語言：一律繁體中文（路徑、程式識別字、CLI 指令、環境變數名保留英文）。
> 欄位規範見 [`docs/CODE_HEADER_SPEC.md`](CODE_HEADER_SPEC.md)。

本檔保存**無法只從語法還原**、且後續維護不得任意改寫的產品／安全決策。

程式中的 `NOTE(NOTE-NNN):` **必須**能在此找到同號條目；若行為改變，需同步更新決策、測試與引用處，**禁止留下失效 reference**。號碼**不重用**，作廢的條目標明作廢日期與原因，不刪除、不重編。

每則必備五欄：**決策日期／適用範圍／決策／原因／驗證**。必要時加**維護邊界**。
**一行摘要不算數**——沒有原因也沒有驗證的條目，追過去等於沒追。

機械檢查：`python -m pytest -q tests\test_repo_integrity.py`

---

## 索引

| # | 標題 | 守的是什麼 |
|---|---|---|
| NOTE-001 | `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 是拒絕清單，不是預設值來源 | `INV-12` 靜默預設模型；`S4.8` 量尺的具名例外 |
| NOTE-002 | agy `--print` 的 prompt 只傳一次 | agy CLI 引數契約 |
| NOTE-003 | 秘密掃描的 `hits` 只回報位置與數量，永不回傳命中的原文 | `INV-04` 金鑰不得寫進 `jobs.json` |
| NOTE-004 | `kind: "cli"` 的 `model` 留空是「不傳參數」，`kind: "api"` 留空是「未設定」 | `INV-12` 不得有預設模型 |
| NOTE-005 | profile 載入錯誤在 agy 模型解析路徑上轉成 note，不轉成例外 | 健康檢查與 CLI 偵測的可用性 |

---

## NOTE-001 `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 是拒絕清單，不是預設值來源

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` 的 `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 與 `configured_antigravity_agy_model()`；`docs/SAI.md` `S4.8` `provider_lock_hits` 量尺的掃描規則；以及下面這份**完整的例外清單**（2026-08-19 實測，共 5 處）：

  | 檔案 | 性質 |
  |---|---|
  | `server.py` | 拒絕清單本體 |
  | `tests/protocol_smoke.py` | 以該值當 fixture，驗證它真的被忽略 |
  | `README.md` | 說明「這個值會被忽略」 |
  | `docs/TOOL_REFERENCE.md` | 同上 |
  | `docs/TROUBLESHOOTING.md` | 同上 |

- **決策**：這個集合裡的模型版本字面值**保留**，上表五處都是 `S4.8` 的**具名例外**。**不得為了讓量尺歸零而刪掉這個集合、改寫成別的形式，或把說明文件裡的值遮掉。**

  **例外的機械判準**（不靠人記得）：`S4.8` 掃描時，**同一行**若出現 `ANTIGRAVITY_LEGACY_UNSAFE_MODELS`、`ANTIGRAVITY_AGY_MODEL` 或 `legacy unsafe` 三者之一，即視為本 NOTE 的例外；其餘一律計入 `provider_lock_hits`。由 `tests/test_repo_integrity.py` 執行。
  ⚠️ **這個判準刻意寫得很窄**。它認的是「這一行在講拒絕清單」，不是「這個檔案可以有模型名」——把整個檔案排除掉，就等於把量尺關掉。
- **原因**：`C9`／`INV-05` 禁的是「架構層用硬編碼模型版本號**決定行為**」。這個集合的作用**正好相反**——它是把一個曾經被寫死進使用者設定的模型值**認出來並丟掉**，好讓 `configured_antigravity_agy_model()` 回傳空字串、不帶 `--model` 參數、由 agy 自己決定要用什麼（`A4.4` 對 `cli` 類角色的處置）。
  刪掉它的後果是：`~/.codex/config.toml` 裡歷史安裝寫入的 `ANTIGRAVITY_AGY_MODEL` 會重新生效，等於把 `INV-12` 要禁的靜默預設模型救回來，而且**沒有任何測試會紅**。
  `S4.8` 的正則抓的是「長得像版本號的字串」，它**分不出「使用它」與「拒絕它」**——這正是量尺需要具名例外、而不是需要改程式的情況。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_antigravity_command_line.py::test_legacy_unsafe_model_is_ignored
  ```
  突變：把 `configured_antigravity_agy_model()` 裡的 `if model in ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 分支拿掉 → **必須變紅**。
- **維護邊界**：要新增被拒絕的模型值，加進這個集合即可，**不需要動 `S4.8`**。但若有人把它改成預設值來源（例如 `model = model or next(iter(ANTIGRAVITY_LEGACY_UNSAFE_MODELS))`），本 NOTE 當場失效，那是 `INV-12` 違規，應直接回退。

---

## NOTE-002 agy `--print` 的 prompt 只傳一次，結尾不得再 append

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` `build_antigravity_command_line()` 的 `style == "agy_print"` 分支。**不含** `ide_chat` 與 `prompt_arg` 兩個分支——那兩個分支的 `command_line.append(prompt)` 是正確的。
- **決策**：`agy_print` 一律以 `command_line += ["--print", prompt, ...]` 傳入 prompt，函式在 `return` 之前**不得**再 `command_line.append(prompt)`。
- **原因**：2026-08-19 合併線上安裝分支時，兩側各有一種合法寫法——舊寫法是 bare `--print` 旗標＋結尾位置參數，新寫法是 `--print <prompt>`。**兩種各自都只傳一次，混在一起就傳兩次**，agy 會把第二份當成另一個引數，行為不可預期。
  這一行的危險在於它**看起來像漏掉了**：讀 `agy_print` 分支的人會看到 `ide_chat` 分支結尾有 `append(prompt)`、`agy_print` 分支沒有，很自然地「補」回去。而 prompt 傳兩次**不會拋例外**，只會讓 agy 收到奇怪的輸入。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_antigravity_command_line.py::test_agy_print_passes_prompt_once
  ```
  突變：在 `agy_print` 分支的 `return` 前加一行 `command_line.append(prompt)` → **必須變紅**。

---

## NOTE-003 秘密掃描的 `hits` 只回報位置與數量，永不回傳命中的原文

- **決策日期**：2026-08-19
- **適用範圍**：`providers/redaction.py` 的 `scan_payload()` 與 `redact_payload()` 回傳的 `hits` 結構；所有把 `hits` 寫進 ledger、job summary 或工具回傳值的呼叫端。
- **決策**：`hits` 的每一筆只含 `pattern`（規則名）、`count`、`firstOffset`、`matchedChars`。**不得**加入 `match`、`sample`、`excerpt`、`value` 之類欄位，即使只放前幾個字元也不行。
- **原因**：`hits` 的用途是「告訴使用者外送被擋了、被什麼規則擋的」，而它會**跟著 job 一起寫進 `%USERPROFILE%\.dev-triangle\jobs.json`**，也會回到 Orchestrator 的對話上下文裡。
  在錯誤報告裡放一小段命中內容是除錯時最自然的動作——**但這裡的命中內容依定義就是金鑰**。那等於偵測器本身成為外洩管道：本來只在記憶體裡待一瞬間的秘密，因為「被抓到了」而被永久寫進帳本，`INV-04`（金鑰不得寫進 `jobs.json`）當場破功。
  截斷也沒用。金鑰的前 8 個字元足以辨識供應商與帳號，而且真正的洩漏往往只需要配上其他線索。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_redaction.py::test_hits_never_echo_the_secret
  ```
  該測試把 canary 金鑰餵進 `redact_payload()`，再把 `hits` 整個序列化成 JSON，斷言 canary 的任何 12 字元以上片段都不在裡面。
  突變：在 `scan_payload()` 的 hit dict 加一個 `"sample": matches[0].group(0)[:12]` → **必須變紅**。
- **維護邊界**：要除錯「為什麼這段被擋」時，正確做法是在本機重跑 `redact_payload()` 自己看，**不是**讓工具把內容送回來。

---

## NOTE-004 `kind: "cli"` 的 `model` 留空是「不傳參數」，`kind: "api"` 留空是「未設定」

- **決策日期**：2026-08-19
- **適用範圍**：`providers/profiles.py` 的 `resolve_role()`；`server.py` 的 `configured_antigravity_agy_model()`；`config/providers.example.json` 的 `diagnostician` 角色。
- **決策**：兩種 `kind` 的空 `model` 走**不同**路徑，**不得統一**：

  | `kind` | `model` 留空的意思 | 程式行為 |
  |---|---|---|
  | `api` | 使用者還沒決定要用哪個模型 | `resolve_role()` raise `RoleNotConfigured`，該角色的工具直接回 `ROLE_NOT_CONFIGURED` |
  | `cli` | 使用者不想干涉，交給那支 CLI 自己決定 | **不傳 `--model` 參數**，正常執行 |

- **原因**：`INV-12` 的規則是「**本專案**不得替使用者決定模型」，不是「一定要有人決定模型」。
  `api` 類沒有模型就無法組出請求，**必須**報錯。
  `cli` 類不一樣：`agy` 本身有它自己的預設，那是**外部工具的決定，不是本專案的決定**。硬要在這裡報錯，等於逼使用者去指定一個他根本不在乎的值；而更糟的做法是隨手挑一個填進去——**那才是 `INV-12` 真正要禁的東西**。
  這兩條路徑長得很像（都是 `if not model:`），所以非常容易被「順手統一」。統一成報錯會讓 agy 路線在沒設 profile 時整條掛掉；統一成放行會讓 `api` 角色帶著空模型去打 API，然後在遠端才炸。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_provider_profile.py::test_cli_role_allows_empty_model tests\test_provider_profile.py::test_empty_model_never_falls_back
  ```
  突變：把 `resolve_role()` 的 `if binding.kind == "api":` 條件拿掉（讓兩類走同一條路）→ **必須變紅**。
- **維護邊界**：未來若新增 `kind`，必須明確決定它屬於哪一類並補一支測試。**不得**讓新 `kind` 落進「兩者皆非」而悄悄放行。

---

## NOTE-005 profile 載入錯誤在 agy 模型解析路徑上轉成 note，不轉成例外

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` 的 `profile_diagnostician_model()` 與 `profile_health_block()`。**不含** `providers/profiles.py` 本身——`load_profile()` 與 `resolve_role()` 一律 raise。
- **決策**：profile 有問題時，這兩個函式回傳／填入一段**人看得懂的錯誤文字**（`agyModelNote`、`profile.status = "PROFILE_ERROR"`），而不是讓例外往上冒。其他所有呼叫端（dispatch 工具、設定工具）維持 raise。
- **原因**：`INV-11` 要求缺 slot key 必須**啟動即報錯，不得靜默略過**，而這則 NOTE 看起來像在違反它——所以要寫清楚差別在哪：
  **「靜默略過」與「大聲回報但不中斷」不是同一件事。** `F10` 怕的是「角色靜靜不被呼叫，流程照跑，沒人知道」；這裡的處置是**把錯誤字串放進使用者一定會看到的回傳值**，它沒有被吞掉。
  反過來說，讓例外冒上去的代價很具體：`antigravity_detect_cli` 與 `mcp_health_check` 是使用者**用來診斷「我的設定是不是壞了」的工具**。它們因為設定壞了而拒絕回答，等於在最需要資訊的時候把資訊關掉。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_provider_profile.py::test_broken_profile_surfaces_as_note_not_crash
  ```
  該測試把 `contextBroker` 改名成 `broker`（`F10` 的實際形狀），斷言 `configured_antigravity_agy_model()` 仍回得了話、且 note 內含錯誤說明；同時斷言 `load_profile()` **有**丟例外。
  突變：把 `profile_diagnostician_model()` 的 `except ProfileError` 改成回 `("", None)`（吞掉錯誤不回報）→ **必須變紅**。
- **維護邊界**：新增的 dispatch 工具**不得**沿用這個處置。它們沒有「使用者正在診斷」的情境，設定壞了就該拒絕執行。
