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

---

## NOTE-001 `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 是拒絕清單，不是預設值來源

- **決策日期**：2026-08-19
- **適用範圍**：`server.py` 的 `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 與 `configured_antigravity_agy_model()`；`docs/SAI.md` `S4.8` `provider_lock_hits` 量尺的掃描規則；`tests/protocol_smoke.py` 設定該環境變數的那一行。
- **決策**：這個集合裡的模型版本字面值**保留**，並在 `S4.8` 的掃描規則中列為**具名例外**（連同 `tests/protocol_smoke.py` 拿它當 fixture 的那一行）。**不得為了讓量尺歸零而刪掉這個集合或改寫成別的形式。**
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
