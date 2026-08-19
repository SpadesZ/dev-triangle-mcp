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
| NOTE-006 | 逾時必須終止整棵行程樹，不是只殺父行程 | 孤兒行程鎖住檔案與埠口 |
| NOTE-007 | `verify.json` 的 hash 必須連 `git HEAD` 一起算 | `VUL-03` TOCTOU；`F4` 惡意 repo |
| NOTE-008 | `S4.9` 的掃描限定在指派與 `return` 位置，比 SAI 的字面 grep 窄 | 量尺不得誤殺，也不得被放寬 |
| NOTE-009 | `cli` 角色的 `args` 逐字照抄，`model` 只是標籤 | 不得內建任何廠商旗標 |
| NOTE-010 | CLI 角色的 `usage` 一律空的，不得補零或估算 | 「花了多少」不能用猜的 |
| NOTE-011 | 不做自動換模型的備援鏈 | 靜默降級；擁有者裁決用 profile 切換 |
| NOTE-012 | `command`／`args` 永遠不可經 NL 通道寫入 | `F17` 從「改端點」升級成「跑任意程式」 |
| NOTE-013 | CLI 的 prompt 預設走 stdin，不走命令列引數 | Windows `.cmd` shim 會切斷多行；命令列有長度上限 |

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

---

## NOTE-006 逾時必須終止整棵行程樹，不是只殺父行程

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` 的 `run_native()`、`kill_process_tree()`、`child_process_spawn_kwargs()`。
- **決策**：子行程一律在自己的 process group／session 中啟動（Windows 用 `CREATE_NEW_PROCESS_GROUP`，POSIX 用 `start_new_session=True`），逾時時對**整個群組**下手（Windows `taskkill /F /T /PID`，POSIX `killpg`），然後才 raise。**不得**改回單純的 `subprocess.run(timeout=...)`。
- **原因**：`subprocess.run` 逾時只會殺掉它直接啟動的那個行程。而 `verify.json` 宣告的指令幾乎都是**啟動器**——`python -m pytest` 會 fork worker、`npm test` 會拉起 node、測試本身可能起一個 dev server。父行程死了，孫行程還活著。
  後果不是「多了幾個閒置行程」，是**下一次驗證會用一個被污染的環境跑**：埠口還被佔著、檔案還被鎖著（Windows 尤其嚴重）、暫存目錄還在被寫。於是驗證結果變成不可重現的，而 `S4.2` `false_green_rate` 的整個前提就是「同樣的指令重跑會得到同樣的結果」。
  這件事在單機開發時幾乎不會被發現——因為第一次跑通常是好的。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_verification_suite.py::test_timeout_kills_the_whole_process_tree
  ```
  該測試讓 suite 跑一個會生出長命子行程的指令並設極短 timeout，逾時後斷言子行程已經不在。
  突變：把 `run_native` 改回 `subprocess.run(..., timeout=timeout)` → **必須變紅**。
- **維護邊界**：`kill_process_tree()` 之後仍要 `communicate()` 把管線抽乾再回傳，否則在 Windows 上會偶發卡住。

---

## NOTE-007 `verify.json` 的 hash 必須連 `git HEAD` 一起算

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` 的 `suite_fingerprint()` 與 `tool_run_verification_suite()` 的確認閘門；ledger 的 `verifySuites[]`。
- **決策**：指紋 = `sha256(verify.json 全文 ‖ git rev-parse HEAD)`。**不得**改成只算 `verify.json` 的內容。
- **原因**：確認閘門要回答的問題是「**我核准過的那件事，跟現在要跑的這件事，是同一件嗎**」。
  只算 `verify.json` 的話，攻擊路徑是這樣的：`verify.json` 寫 `python -m pytest`，你看過、確認了；接著一個 patch 把 `tests/conftest.py` 換掉。`verify.json` 一個字都沒動，指紋不變，閘門直接放行——而真正被執行的程式碼已經完全不同了。**這就是 `VUL-03` 的 TOCTOU**：檢查的是宣告，執行的是內容。
  把 HEAD 綁進去之後，任何 commit 都會讓指紋改變，於是「換掉測試腳本」必然伴隨一次重新確認。
  代價是誠實的：**每次 commit 之後第一次驗證都要重新確認一次**。這個摩擦是刻意的，不得為了順手而拿掉。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_verification_suite.py::test_new_commit_requires_reconfirmation
  ```
  突變：把 `suite_fingerprint()` 改成只吃 `manifest_text` → **必須變紅**。
- **維護邊界**：這道閘門**不受**「設定變更不設閘門」那道裁決（`I4` gate #8／#9）涵蓋。那道裁決講的是**使用者設定自己的工具**；這道擋的是**第三方 repo 的檔案能不能在你的機器上跑指令**。詳見 `docs/decisions/2026-08-19-three-vendor-upgrade.md`。

---

## NOTE-008 `S4.9` 的掃描限定在指派與 `return` 位置，比 SAI 的字面 grep 窄

- **決策日期**：2026-08-19
- **適用範圍**：`tests/test_repo_integrity.py` 的 `SILENT_DEFAULT_PATTERNS` 與 `is_silent_default()`；`docs/SAI.md` `S4.9` 的量法。
- **決策**：`silent_default_count` 只計算**指派**（`model = ... or "..."`）與 **`return`**（`return ... or "..."`）兩種位置，不計算所有出現 `model`／`baseUrl`／`provider` 又出現 `or "..."` 的行。此偏離必須由 `test_silent_default_detector_actually_detects` 同時證明「該抓的抓得到」與「不該抓的沒抓」。
- **原因**：SAI `S4.9` 給的量法是字面 grep，2026-08-19 首次執行時在乾淨的程式碼上命中兩處，**兩處都不是它要抓的東西**：
  - `"id": short_id(provider or "job")` —— `provider` 在這裡是 job id 的前綴，`"job"` 是前綴的預設值，跟模型無關。
  - `f"...{changes['baseUrl'] or '(adapter default)'}"` —— 這是**警示訊息裡的顯示字串**，用來告訴使用者「原本沒設，所以走 adapter 內建端點」。它不決定任何行為。

  一個會誤殺的量尺跟一個永遠是綠的量尺一樣沒用：真正的違規混在誤報裡，下一個人只會把整條檢查關掉。
  **但收窄有風險**：收窄的動作本身就是「放寬量尺」最常見的偽裝。因此這則 NOTE 的驗證欄不只驗違規抓不抓得到，還把**兩個被放行的形狀逐字寫進測試**——要再放寬就必須動那支測試，而動它會被看見。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_repo_integrity.py::test_silent_default_detector_actually_detects
  ```
  該測試斷言三種真違規（`model = ... or`、`base_url = ... or`、`return ... or`）都抓得到，且上述兩個被放行的形狀不會命中。
  突變：把 `SILENT_DEFAULT_PATTERNS` 清空 → **必須變紅**。
- **維護邊界**：要再排除新的形狀，必須（a）在此列出那一行的原文與它為什麼不決定行為，（b）在測試裡加一條對應的 `assert not is_silent_default(...)`。**不得**直接放寬正則或整個檔案排除。

---

## NOTE-009 `cli` 角色的 `args` 逐字照抄，`model` 只是標籤

- **決策日期**：2026-08-19
- **適用範圍**：`providers/cli_agent.py` 的 `build_command()`；`providers/profiles.py` 的 `args`／`prompt_arg` 欄位；`config/providers.example.json` 的 `cli` 角色註解。
- **決策**：CLI 指令列一律組成 `[command, *args, promptArg, prompt]`，`args` **逐字照抄使用者填的清單**。本專案**不得**為任何 CLI 內建旗標——不猜「這家要用 `--model`、那家要用 `-m`」。`cli` 角色的 `model` 欄位**只是給人看與記帳用的標籤**，不會被組進指令列。
- **原因**：這一層存在的理由是「使用者手上有哪支 CLI，就用哪支」。一旦開始替各家猜旗標，就等於本專案宣稱自己知道那些 CLI 的介面——而那些介面**會改版，而且改版時不會通知這個 repo**。到時候壞掉的形狀是：指令跑起來了、旗標被忽略或報錯、使用者以為用的是 A 模型其實是預設模型。
  逐字照抄的代價是使用者要自己寫對 `args`，但**寫錯會立刻炸**（CLI 自己會抱怨未知旗標），而不是安靜地跑錯。**會吵的錯誤勝過安靜的錯誤。**
  `model` 不進指令列也是同一個理由：真要指定模型，使用者把 `--model X` 放進 `args` 就好，那是他那支 CLI 的語法，不是本專案發明的。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_cli_agent.py::test_args_are_passed_verbatim tests\test_cli_agent.py::test_model_is_a_label_not_a_flag
  ```
  突變：在 `build_command()` 裡加 `if binding.model: line += ["--model", binding.model]` → **必須變紅**。
- **維護邊界**：要支援某支 CLI 的特殊呼叫形狀（例如 prompt 要走 stdin 而不是引數），正確做法是新增一個 `kind`，不是在 `cli` 裡加分支判斷廠商。

---

## NOTE-010 CLI 角色的 `usage` 一律是空的，不得補零或估算

- **決策日期**：2026-08-19
- **適用範圍**：`providers/cli_agent.py` `run_agent()` 的回傳；`tool_usage_summary` 的彙總欄位；`job.cost`。
- **決策**：CLI 路徑回傳的 `usage` **一律是空 dict**。不得填 `{"input_tokens": 0}`，不得用字元數估算 token，不得從 CLI 的 stdout 猜。用量彙總必須把這種來源標成 `tokensAvailable: false`，而不是顯示 0。
- **原因**：訂閱制的 agent CLI 不回報 token 數——那是它的計費模型決定的，不是本專案能補的資訊。
  補 0 的後果很具體：`tool_usage_summary` 會顯示「architect 這個月花了 0 token」，而使用者的**真實結論會是「這條路線不花錢」**。它其實在燒訂閱額度，只是這裡量不到。**一個顯示 0 的欄位比一個明說「量不到」的欄位更危險**，因為前者看起來像已經量過了。
  估算更糟：字元數換 token 的誤差在程式碼與多語言內容上可以到兩三倍，而一旦有數字，下一個人就會拿它做決策。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_cli_agent.py::test_cli_usage_is_empty_not_zero
  ```
  突變：把 `run_agent()` 的 `"usage": {}` 改成 `{"input_tokens": 0, "output_tokens": 0}` → **必須變紅**。
- **維護邊界**：哪天某支 CLI 真的開始回報 token（例如加了 `--json` 輸出用量），那時才把它解析出來填進 `usage`——**解析得到才填，解析不到維持空的**。

---

## NOTE-011 不做自動換模型的備援鏈

- **決策日期**：2026-08-19
- **適用範圍**：`providers/dispatch.py`；未來任何想在 `send()` 外面包一層「這家失敗換那家」的程式碼。
- **決策**：`dispatch.send()` 失敗就是失敗，**不自動換到另一個 provider 或另一個模型**。額度用完、429、CLI 不存在，一律把錯誤原樣往上報，由使用者決定換哪一組——換的方式是切 profile（`W15`），不是系統自己挑。
  `send_expecting_json()` 的重問是**同一個 binding 重問一次格式**，不是換人，兩者不要混為一談。
- **原因**：擁有者於 2026-08-19 明確裁決「不做備援鏈，用 profile 切換」。理由不是備援做不出來，是**靜默降級**：M1 是貴的好模型、M3 是便宜的，自動掉下去會讓產出品質悄悄變差，而 ledger 上一路綠燈。
  這與 `INV-15(c)`（派送顯示去向）表面上可以緩解——去向欄位會顯示實際用了誰——但那只在使用者**回頭看**的時候有效；自動降級發生在無人看管的長跑裡，而那正是它最會出事的時候。
  **把「換誰」留在使用者手上，是這個決策唯一的內容。**
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_cli_agent.py::test_dispatch_does_not_fall_back
  ```
  該測試讓一個 binding 必定失敗，斷言 `DispatchError` 往上冒且沒有第二個 binding 被呼叫。
  突變：在 `send()` 加一個 `except ... : return send(other_binding, ...)` → **必須變紅**。
- **維護邊界**：`send_expecting_json` 的「重問一次」是格式重問，上限寫死 1 次。要改成重問兩次以上必須先回答「為什麼第二次會比第一次好」，否則那就是沒有煞車的迴圈。

---

## NOTE-012 `command` 與 `args` 永遠不可經 NL 通道寫入

- **決策日期**：2026-08-19
- **適用範圍**：`providers/profiles.py` 的 `WRITABLE_ROLE_FIELDS`；`server.py` 的 `NL_WRITABLE_FIELDS` 與 `tool_profile_set_role` 的參數表。
- **決策**：`command`、`args`、`promptArg`、`kind` **一律不列入可由 `profile_set_role` 寫入的欄位**，只能由使用者親手編輯 `config/providers.<name>.json`。
- **原因**：`W13` 之後，設定變更**不設閘門**（擁有者裁決 gate #8／#9），已接受的殘餘風險是 `F17`：一段藏在 repo 內容或錯誤 log 裡的文字，可以讓 Orchestrator 相信「使用者要求改設定」。
  在 `W14` 之前，`F17` 的最壞結果是**把 brief 送到別的端點**——嚴重，但邊界是「資料外流」。
  一旦 `command` 可經 NL 寫入，同一段注入文字的最壞結果變成**在這台機器上執行任意程式**。那不是同一個等級的風險，是**跨越了 `INV-01` 那條線**——本專案花了 `W03` 一整包的力氣，才讓「執行本機指令」限縮成「目標 repo 自宣告的白名單」，如果 NL 可以指定任意可執行檔，那道限制就被從側面繞過了。
  ⚠️ **注意這與 gate #8「我的 NL 就是最高權限」不衝突。** 那道裁決解除的是「**使用者設定自己的工具**」這條路上的確認；它明文**不解除** `verify.json` 的 hash 閘，理由是那道閘擋的不是使用者、是「別人的檔案能不能在你的機器上跑指令」。`command` 屬於**後者**：工具分不出那句話是使用者講的還是 repo 裡的文字，而後果是執行任意程式。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_cli_agent.py::test_command_is_never_nl_writable
  ```
  該測試斷言 `command`／`args`／`promptArg`／`kind` 都不在 `profile_set_role` 的 schema 裡，且直接呼叫 `update_role_in_file` 傳入 `command` 會被拒絕。
  突變：把 `command` 加進 `WRITABLE_ROLE_FIELDS` 或 `NL_WRITABLE_FIELDS` → **必須變紅**。
- **維護邊界**：使用者想用講的換 CLI 時，正確答案是「我幫你把 `config/providers.<name>.json` 打開，你自己改那一行」，或是預先在檔案裡準備好多個 profile 再用 `profile_activate` 切（`W15`）——**切換一組事先由人審過的設定是安全的，憑空指定一個可執行檔不是。**

---

## NOTE-013 CLI 的 prompt 預設走 stdin，不走命令列引數

- **決策日期**：2026-08-19
- **適用範圍**：`providers/cli_agent.py` 的 `run_agent()`／`build_command()`；`providers/profiles.py` 的 `promptVia` 欄位（預設 `"stdin"`）；`server.py` `run_native()` 的 `input_text` 參數。
- **決策**：CLI 角色的 prompt **預設由 stdin 送入**。`promptVia: "arg"` 是給少數只吃引數的 CLI 的逃生口，**不得改成預設**。
- **原因**：這是 2026-08-19 寫測試時**在 Windows 上實際踩到的**，不是預防性設計。

  `test_real_cli_receives_the_expected_argv` 第一版把 prompt 當成 argv 元素傳，斷言失敗：

  ```
  assert 'USER' in argv[2]
  AssertionError: assert 'USER' in 'SYS'
  ```

  prompt 是 `SYS\n\n---\n\nUSER`，經過 Windows 的 `.cmd` shim（`%*` 由 cmd.exe 重新解析）之後**在換行處被切成兩個引數**，下游只收到前半段。而 **npm 安裝的 agent CLI 在 Windows 上幾乎都是 `.cmd` shim**，所以這不是測試造出來的人工情境，是這條路線在 Windows 上的預設情境。

  第二個理由與平台無關：Windows 命令列**總長度上限約 32KB**，而 `context_broker` 送出去的 repo outline 上限就設在 `MAX_DIGEST_CHARS = 40000`。也就是說即使沒有換行問題，**這個 payload 本來就超過命令列裝得下的大小**。

  兩件事合起來的結論是：**命令列從來就不是這個 payload 的正確通道**。真正的 agent CLI 也是這樣設計的——它們吃 stdin，正因為 prompt 又長又多行。
- **驗證**：
  ```powershell
  python -m pytest -q tests\test_cli_agent.py::test_multiline_prompt_survives_via_stdin
  ```
  該測試用一支真的假 CLI（Windows 上就是 `.cmd` shim），送一個帶換行的 prompt，斷言完整內容原封抵達。
  突變：把 `prompt_via` 的預設從 `"stdin"` 改成 `"arg"` → **必須變紅**（在 Windows 上；POSIX 上換行可以存活，所以該測試另外斷言 payload 長度超過命令列上限的情境）。
- **維護邊界**：`promptVia: "arg"` 保留給真的只吃引數的 CLI，但用它時 payload 長度風險由使用者承擔。**不得為了「看起來比較直觀」把預設換回引數。**
