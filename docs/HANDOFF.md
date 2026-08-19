# HANDOFF — 三廠協作升級（2026-08-19 施工輪）

> 檔案路徑：`docs/HANDOFF.md`
> 分支：`feat/sai-v0.6-upgrade`（自 `main` 分出，領先 22 個 commit ＋ 併入 4 個線上分支 commit）
> 依據：`docs/SAI.md` v0.6 的 `W00`–`W13`，加上施工後追加的 `W14`–`W18`
> 語言：一律繁體中文（路徑、程式識別字、CLI 指令保留英文）。

**這份檔案是什麼**：讓下一個人（或下一輪的我）不必重新逆推就能接手。
**這份檔案不是什麼**：不是規範（規範在 `docs/SAI.md`）、不是決策理由（在 `docs/NOTES.md`）、不是裁決紀錄（在 `docs/decisions/`）。

---

## 一、現在站在哪裡

| 項目 | 值 |
|---|---|
| 分支 | `feat/sai-v0.6-upgrade`，**未推、未合併 `main`** |
| MCP 工具數 | **30**（施工前 19） |
| 測試 | `python -m pytest -q tests` → **155 passed**，15 個 `test_*.py` |
| 突變驗證 | **52 條全部紅→綠**，逐條記在各包的 commit message |
| `providers/` | 10 個模組 |
| `docs/NOTES.md` | 13 則，全部有同號完整條目與可執行驗證 |
| 本機安裝 | Codex 已指向 `D:\dev-triangle-mcp`，`doctor.ps1` **pass**（11 項全綠） |

### 一句話狀態

**「假綠燈」那條核心已經補起來並實跑驗證過；「彈性化」的機制做完了但只有 mock 證據。**

---

## 二、動手前必讀的三件事

### 1. 這台機器上曾經有兩份會各自被改的 checkout

- `D:\dev-triangle-mcp` —— **現在的真相來源**
- `C:\Users\Franky Kuo\DevTools\dev-triangle-mcp` —— 舊的線上安裝位置，**已降為歷史備份，不要再改它**

2026-08-19 已把 DevTools 那條分支（+386 行：空 stdout 處理、transcript／conversation DB 結果回收）合併進來（commit `ea52d12`），13 處衝突全採 DevTools 側。

⚠️ **`scripts\install-local.ps1` 只寫設定、不複製檔案。** 它把 `-ToolRoot` 的絕對路徑寫進客戶端設定，所以「你在哪個資料夾改程式」跟「客戶端實際載入哪一份」是兩件事，改錯地方**不會有任何錯誤訊息**。動手前先跑 `.\scripts\doctor.ps1`。

### 2. 驗證環境

```powershell
python --version        # 3.12.10，pytest 9.1.1
py -3.10 --version      # 3.10.11，pytest 9.0.3（兩邊都有 pytest）
```

repo **沒有 venv**。測試會把狀態寫到臨時目錄（`tests/conftest.py` 在 import 前就改掉 `DEV_TRIANGLE_HOME`），不會碰 `%USERPROFILE%\.dev-triangle`。

### 3. 每一包都要有突變驗證

`docs/SAI.md` `I0.3`：拿掉修法測試必須變紅，還原後回綠，且**斷言要指名分支**。
本輪工具在 `C:\Users\FRANKY~1\AppData\Local\Temp\claude\...\scratchpad\mutate.py`（session 結束會消失，重寫很簡單：讀檔、確認樣板剛好出現一次、替換、寫回）。

⚠️ **本輪有四次突變第一次跑出綠燈**，全部是測試自己有洞，不是程式對：

| 突變 | 為什麼沒紅 | 怎麼補的 |
|---|---|---|
| `job_with_defaults` 改成就地填充 | 測試只做 load→save，從沒經過 `job_with_defaults` | 補走真正危險順序的測試（同一個 ledger 物件 load→view→save） |
| 回報伺服器不標 `agent_asserted` | `report_server_smoke` 從沒斷言過該欄位 | 補斷言 |
| `S4.9` 偵測器清空 | 我的突變寫法有誤（`() or (...)` 仍回原值） | 改成讓函式直接回 `False` |
| CLI／API 混合列的 token 汙染 | 測試前提錯了（分組鍵含 `kind` 與 `targetModel`，本來就該分兩列） | 改用真實情境：同一 binding 某些回應沒帶 usage |

**教訓**：全綠不代表守住了，要先確認那支測試真的走過那條路徑。

---

## 三、做完了什麼

### 核心（假綠燈）—— 有實跑證據

| 包 | 內容 |
|---|---|
| `W03` | `run_verification_suite`：只跑目標 repo 自宣告的 `.dev-triangle/verify.json`，呼叫端**沒有** `command` 參數；指紋 = `sha256(verify.json ‖ git HEAD)`；逾時殺整棵行程樹 |
| `W04` | Quality Gate：`SUCCESS` 必須 `evidenceLevel == machine` ＋ `exitCode == 0` ＋ primary suite |
| `W02` | ledger schema v2，additive，**不遷移**舊資料 |
| `W01` | Provider Profile 載入器，鏈的末端是報錯不是預設值 |
| `W08` | 外送遮罩，一份規則兩邊共用 |

**實跑證據**（隔離的 `DEV_TRIANGLE_HOME`）：

```
代理人自述 requested SUCCESS  → NEEDS_REVIEW
run_verification_suite default suite → exitCode 0, evidenceLevel machine (13.79s, 3 條指令)
機器憑據 requested SUCCESS    → SUCCESS
S4.1 machine_verified_rate = 1.000 (1/1)
```

### 兩棒與 self-heal —— 只有 mock 證據

`W05` Context Broker、`W06` Architect ＋ `apply_patch`、`W07` self-heal、`W13` NL 設定橋接。
⚠️ **每一支測試都替換掉傳輸層**，從未對真實端點送出過任何請求。

### 彈性化（`W14`–`W18`，施工後追加）

| 包 | 內容 |
|---|---|
| `W14` | CLI agent 解耦：`kind: "cli"` 可綁到任何角色；`dispatch.py` 依 kind 路由；`start_job` 接通 `architect-only` |
| `W15` | `profile_activate` 整包切換，落 `config/active-profile.json`（**檔案贏過環境變數**） |
| `W16` | `doctor.ps1` 的 `orchestratorConfigured`：Codex 或 Claude 任一指向本 ToolRoot 即通過 |
| `W17` | `install-local.ps1 -Orchestrator codex\|claude\|both` |
| `W18` | `usage_summary`：calls 與 tokens **分兩欄**，CLI 列標 `tokensAvailable: false` |

### 規範落地

- 全 repo 30 個 `*.py`／`*.ps1` 都有繁中十欄檔頭
- `tests/test_repo_integrity.py` 把「檔頭齊全／`驗證方式` 指到的檔案存在／`NOTE-NNN` 找得到同號條目／每則 NOTE 五欄齊全／`S4.8` = 0／`S4.9` = 0」變成會紅的檢查

---

## 四、**沒有**做完的（誠實清單）

### 1. `C6`「not only mocks」未達成 —— 最重要的一條

`docs/PROVIDERS.md` 的 profile 狀態表**刻意沒有改成 stable**（`INV-10`）。六條驗收裡五條綠、第六條紅，而那正是「not only mocks」要擋的四捨五入。

**要補這條，最省的路徑**（不需要 API key）：

```powershell
# 1. 把 architect 綁到你已經有的 CLI
#    編輯 config/providers.<name>.json 的 architect：
#      "kind": "cli", "command": "claude", "promptArg": "-p", "promptVia": "stdin", "enabled": true
# 2. 開一個 architect-only 的 job，直接指定要讀哪些檔
#    然後 dispatch_architect → apply_patch → run_verification_suite
```

跑通一次就是這條路線第一次的真實證據。

### 2. Claude 端已用 `.mcp.json` 掛上（`claude_desktop_config.json` 這條路是死的）

**現況**：`doctor.ps1` 回報 `orchestratorConfigured  codex, claudeCodeProject`。
在 `D:\dev-triangle-mcp` 開 Claude Code、核准伺服器之後，30 支工具就會出現。

實測（2026-08-19，用 `.mcp.json` 裡的設定實際啟動）：

```
ledgerPath : C:\Users\Franky Kuo\.dev-triangle\jobs.json   ← 共用帳本，不是 fallback
tool count : 30
```

⚠️ **`claude_desktop_config.json` 那條路走不通，別再試。** 安裝當下 `doctor.ps1` 確實回報
`claudeDesktop` PASS，三小時後那個鍵自己消失了——檔案大小精確回到安裝前的 14016 bytes，
App 用自己的狀態重寫了整個檔。詳見 `NOTE-014`，那則 NOTE 存在的目的就是擋住下一個人
「幫忙把它加回來」。

**還沒做的是 user scope**（讓 dev_triangle 在**所有**專案都看得到，不只 `D:\dev-triangle-mcp`）：

- `claude` CLI **不在本機 PATH 上**（`where.exe` 找不到，常見安裝位置都沒有），所以
  `claude mcp add` 這條在這台機器上跑不了。
- `~/.claude.json` 目前**沒有 `mcpServers` 鍵**。要手動加的話**先關掉 Claude Code**——
  它會重寫那個檔（41.5 KB，含 `projects` 歷史與 `oauthAccount`），開著改會被吃掉，
  跟上面 desktop 的情況一模一樣。

⚠️ **這道指令一定要帶 `-e`。** `server.py` 在沒有 `DEV_TRIANGLE_HOME` 時會退回
`<ToolRoot>\.dev-triangle`，實測：

```
沒有 DEV_TRIANGLE_HOME  → D:\dev-triangle-mcp\.dev-triangle\jobs.json  （空的）
Codex 與 Claude Desktop → C:\Users\Franky Kuo\.dev-triangle\jobs.json  （jobs=12, handoffs=18）
```

也就是說少了那個環境變數，**Claude Code 會自己記一本空帳，而且不會有任何錯誤訊息**——
跟這一輪一開始 `D:` 與 `DevTools` 兩份 checkout 分岔是同一類無聲失效，只是這次分岔的是帳本。

安裝器現在印出的完整指令（`notes` 欄）：

```powershell
claude mcp add dev-triangle --scope user `
  -e DEV_TRIANGLE_HOME="C:\Users\Franky Kuo\.dev-triangle" `
  -e ANTIGRAVITY_HANDOFF_DIR="C:\Users\Franky Kuo\.dev-triangle\antigravity-handoffs" `
  -e ANTIGRAVITY_COMMAND="C:\Users\Franky Kuo\AppData\Local\agy\bin\agy.exe" `
  -- "<python>" "D:\dev-triangle-mcp\server.py"
```

**Claude Code 那邊刻意不由腳本改寫** `~/.claude.json`（41.5 KB，含 `projects` 歷史與
`oauthAccount`，是 Claude Code 自己擁有並持續重寫的檔）。若你的 `claude` CLI 不吃 `-e`，
就手動在 `~/.claude.json` 加一個 `mcpServers` 條目——**形狀與
`%APPDATA%\Claude\claude_desktop_config.json` 完全相同**，照抄即可。

跑完後 `doctor.ps1` 的 `orchestratorConfigured` 應再多出 `claudeCode`。

### 3. CI 只做過本機模擬

`.github/workflows/ci.yml` 已加入 pytest 步驟，並用本機模擬證明「刪掉那一步，一個被拆掉的 `INV-03` 檢查可以完整通過 CI」。**但分支沒推，沒有真實的 GitHub Actions 紅綠紀錄。**

### 4. `scripts\demo-user-flow.ps1` 未實跑（需本機已認證的 agy）

### 5. 尚未回覆的 owner gate

記在 `docs/decisions/2026-08-19-three-vendor-upgrade.md`，目前全部照 SAI 預設值走：

| gate | 待裁決 | 目前採用的預設 |
|---|---|---|
| #2 | 是否移除 Jules | 不移除 |
| #5 | Quality Gate 上線後大量轉 `NEEDS_REVIEW` 可否接受 | 可接受（量尺變準不是系統變壞） |
| #7 | `C1`–`C11` 全綠後是否對外宣稱 stable | 無預設，目前不宣稱 |
| #10 | `scope` 由必填改為預設永久 | 預設永久 |

已裁決：#1（允許白名單 runner）、#3（只允許 `<self>` 外送）、#4（`maxAttempts = 1`，硬鎖 3）、#6（模型由使用者指定）、#8／#9（NL 不設閘門）。

---

## 五、接手時最容易踩的坑

1. **不要把 `NOTE-001` 的模型字面值當成違規刪掉。** `ANTIGRAVITY_LEGACY_UNSAFE_MODELS` 是**拒絕清單**，刪掉會讓舊安裝設定裡的模型值復活。`S4.8` 的例外判準是「同一行出現三個識別字之一」，**不是整檔排除**。
2. **不要把 `command` 加進可經 NL 寫入的欄位。** 見 `NOTE-012`：那會讓注入式設定變更從「改端點」升級成「跑任意程式」，從側面繞過 `INV-01`。
3. **不要把 CLI 的 token 數補 0。** 見 `NOTE-010`：報表上最便宜的那一列會剛好是沒人看得到成本的那一列。
4. **不要把 CLI 的 prompt 改回走命令列引數。** 見 `NOTE-013`：Windows `.cmd` shim 會在換行處切斷，而且命令列上限 32KB < outline 上限 40000 字元。
5. **不要加自動備援鏈。** 見 `NOTE-011`：擁有者裁決用 profile 切換；自動降級會讓品質悄悄變差而帳面全綠。
6. **`W12` 是 `W03` 的合併前置。** 憲章措辭與程式碼的矛盾不會有任何測試變紅，只有 `tests/test_charter_consistency.py` 擋得住。

---

## 六、快速指令

```powershell
cd D:\dev-triangle-mcp

# 全套驗證
python -m pytest -q tests
python tests\protocol_smoke.py
python tests\report_server_smoke.py
.\scripts\smoke.ps1 -StateRoot $env:TEMP\dt-smoke
.\scripts\doctor.ps1

# 兩把量尺（也在 test_repo_integrity.py 裡）
python -m pytest -q tests\test_repo_integrity.py

# 用這套自己驗自己（機器憑據路徑）
$env:DEV_TRIANGLE_HOME = "$env:TEMP\dt-verify"
python -c "import server; print(server.tool_run_verification_suite({'repoPath': r'D:\dev-triangle-mcp', 'suiteName': 'default', 'confirmSuite': True})['status'])"
```

## 七、相關文件

```
docs/SAI.md                 ← 規範（S/A/I 三部曲、INV-*、C1–C11、W00–W13）
docs/NOTES.md               ← 13 則決策理由，程式裡的 NOTE(NOTE-NNN) 指向這裡
docs/CODE_HEADER_SPEC.md    ← 十欄檔頭與 NOTE 規範
docs/decisions/2026-08-19-three-vendor-upgrade.md  ← owner gate 裁決書
docs/ROLE_MODEL.md          ← 角色契約（含 W09 的 Jules 護欄盤點）
docs/PROVIDERS.md           ← profile 狀態表（含 C1–C11 逐條證據）
docs/HANDOFF.md（本檔）      ← 接手指南
```
