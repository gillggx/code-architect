Code Edit Agent 強化技術規格書 (v3.5)
文件狀態： 待開發 (Target: Sprint 3)
目標： 實作具備「高準確度、自我驗證、深層 Context 感知」的自動化程式碼編輯管線。

1. 核心架構：四階段執行管線 (The Pipeline)
為了拉近與 Claude Code 的差距，Agent 必須遵循嚴格的線性邏輯，禁止直接「跳寫」程式碼。

Stage 1: Context Exploration (上下文檢索)

行為： Agent 接收 Task 後，禁止立即修改。必須先呼叫 list_files 或 grep 掃描專案。

輸入： 使用者原始需求。

輸出： Agent 的內部思維（Thought），列出它認為相關的檔案與符號（Symbols）。

Stage 2: Structural Planning (結構化規劃)

行為： 在進行任何 write_file 前，Agent 必須產出一份 Markdown Plan。

前端呈現： 專用的 PlanCard 供使用者核准（Approve/Reject/Modify）。

必備要素： * 受影響檔案清單。

依賴關係預判（基於 Dependency Graph）。

預計執行的 Tool Call 序列。

Stage 3: Atomic Execution & Syntax Check (原子執行與語法檢查)

行為： Agent 執行修改。每完成一個 edit_file 工具調用，後端自動觸發 verify_syntax。

自癒機制 (Self-Correction)： 若語法錯誤（如 AST 解析失敗），Agent 必須收到 Error Result 並自動重新嘗試修改，上限為 3 次。

Stage 4: User Review & Apply (使用者審核)

行為： 提供 Side-by-Side Diff 檢視，使用者可針對單一檔案 Apply 或 Skip。

2. 工具箱擴充 (The Toolbelt)
必須在 src/architect/api/tools/ 新增或升級以下工具：
工具名稱,功能描述,關鍵邏輯
read_symbol_context,讀取特定 Class/Function,利用現有的分析索引，精準抓取定義，不浪費 Token 讀取整檔。
check_dependency,查詢模組下游依賴,"調用 DependencyGraph 資料，告訴 Agent：「如果你改了這個 Base 類別，會影響 C, D, E 檔案」。"
syntax_lint,靜態語法檢查,Python 使用 ast.parse，TS/JS 使用 tsc --noEmit。
edit_file_patch,精準局部修改,捨棄全檔覆寫，改用 Search-and-Replace 或 Line-level patch，減少長文本出錯率。

3. 後端 API 規格
3.1 建立編輯會話

POST /api/agent/session

Request: { project_id: string, task: string, mode: "interactive" }

Response: { session_id: string, status: "thinking" }

3.2 SSE 事件流 (Event Stream)

GET /api/agent/session/{id}/events

event: plan — 傳送 Markdown 計畫。

event: tool_use — 傳送當前正在執行的動作（如 Reading file A...）。

event: diff_generated — 產出一個檔案的 Diff 資料。

event: error — 語法錯誤或工具執行失敗。

event: finished — 流程結束。

4. System Prompt 核心邏輯 (The Intelligence)
這是決定 Agent 「聰不聰明」的關鍵。Prompt 必須包含：

Identity: 你是一位精通軟體架構的 Senior Principal Engineer。
Operational Rules:

No Guessing: 嚴禁猜測變數名稱或 Import 路徑。若不確定，必須使用 grep 或 read_symbol_context。

Dependency Awareness: 每次修改前，先評估對其他模組的副作用。

Step-by-Step: 必須先提出 Plan 並獲得批准，才能開始產出 Code。

Incrementalism: 優先進行小步修改，每完成一個邏輯單元即進行驗證。

5. 前端互動 (UI/UX)
5.1 Edit Tab 元件

ChatBar: 置於底部，用於輸入指令。

Progress Stepper: 顯示 Analyzing -> Planning -> Executing -> Verified。

Plan Card: * 列出勾選清單（Checkbox），讓使用者決定哪些檔案交給 Agent 改，哪些不要。

[Proceed] / [Adjust Plan] 按鈕。

Diff Card:

顯示 filename 與 diff-view。

狀態標記：[Pending] / [Applying] / [Syntax OK] / [Error: Line 45].

6. 邊界情境與異常處理 (Boundary Cases)
Token Limit: 若專案太大，強制 Agent 只能在單次 Session 讀取最多 15 個檔案。

State Mismatch: 若使用者在 Agent 思考時手動改了檔案，執行 edit_file 前必須比對 mtime。若不一致，強制 Agent 重新 read_file。

Infinite Loop: 自我修正次數上限設為 3，若 3 次都修不好，暫停並請求人工介入。

7. 驗收清單 (Acceptance Criteria)
[ ] 正確性： Agent 產出的程式碼必須通過靜態語法檢查（Linting）。

[ ] 安全性： 禁止任何會修改 .git 或專案目錄外檔案的 Tool Call。

[ ] 透明度： 使用者能清楚看到 Agent 為什麼要這樣改（思維鏈）。

[ ] 互動性： 使用者點擊 Apply 後，檔案內容確實寫入硬碟並同步更新 FileTree 的 modified 標記。