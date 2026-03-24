Code Architect Agent 2.0 系統規格書 (Spec)
1. 系統願景 (Vision)
從「被動摘要」轉向「主動導航」。Agent 不再只是紀錄 Code 在幹嘛，而是理解 變更影響 (Impact)、業務合約 (Contract) 與 驗證手段 (Testability)。
2. 核心架構：三層記憶機制 (Tiered Memory)
記憶層級,儲存內容,更新頻率,目的
L1: Project Vibe (Static),命名規範、架構模式、禁止事項、核心技術棧。,專案初始化時一次。,確保 AI 生成的 Code 風格一致。
L2: Structural Map (Dynamic),檔案依賴關係圖 (Dependency Graph)、Exported APIs、資料流向。,每次 Git Commit 或檔案變更。,定位修改點與評估影響範圍。
L3: Just-In-Time Snippets,原始碼切片 (Code Snippets)、Context-rich Blocks。,任務觸發時即時讀取。,提供 LLM 最精確的邏輯細節。

3. 模組功能設計 (Functional Modules)
A. 解析模組 (Enhanced Parser)

不再寫「摘要」，而是提取 「合約」。

Input: Source Code.

Output (JSON Metadata):

Public_Interfaces: 暴露出的函式與參數類型。

Pre_Conditions: 進入此邏輯前必須滿足的條件（如：User 需登入）。

Side_Effects: 是否改動資料庫、發送 Notification 等。

Critical_Path: 此檔案是否屬於核心路徑（如：支付流）。

B. 導航模組 (Impact Navigator)

當使用者輸入需求（如：「我想改掉登入邏輯」）時：

Keyword Search: 搜尋 L2 記憶，找出相關 Symbols。

Upstream/Downstream Analysis: 列出受影響的相依檔案。

Path Recommendation: 建議修改順序（例如：先改 Interface A，再改實作 B）。

C. 驗證模組 (Test-Driven Validation)

[落實測試腳本原則]：

功能： 為每個核心模組生成一個 <file_name>_vibe_check.py 或 .ts。

內容： 極簡的測試邏輯（5-10 行），用來驗證該檔案的核心假設。

目的： 當 Agent 修改 Code 後，自動跑這段腳本確認「底層邏輯」沒壞。

4. 下一步建議之實作細節
第一步：重寫解析 Prompt (The Architect Prompt)

將 Agent 的 System Prompt 修改為：

「你現在是資深架構師。你的任務不是摘要程式碼，而是建立『導航地圖』。請針對每個模組輸出：

業務規則：這段 Code 隱含的商業邏輯為何？

脆弱點：這裡最容易因為什麼變動而壞掉？

相依性：誰叫它？它叫誰？」

第二步：設計動態 RAG 檢索邏輯

問題： 傳統 RAG 只看文字相似度，對 Code 很弱。

解法： 引入 AST (Abstract Syntax Tree) 輔助。

當使用者問「訂單怎麼成立」時，Agent 先查 L2 的 Structural Map。

定位到 OrderService，然後把 OrderService 及其 Dependencies 的程式碼直接丟給 LLM。

第三步：整合「測試腳本」生成流

Workflow: 1.  Agent 解析原始碼。
2.  Agent 提取該檔案的 Critical Logic（核心邏輯）。
3.  Agent 自動生成一個極簡的 Smoke Test。
4.  當 User 要求修改時，Agent 會先說：「我已準備好驗證腳本，修改後我會執行它以確保邏輯正確。」

5. 實施指標 (Success Metrics)
減少重複讀取次數： 使用者是否能在不打開原始碼的情況下，精確判斷出修改哪幾行會生效。

準確度： Agent 預測的「修改影響範圍」與實際修改的檔案重疊率是否超過 80%。

信心值： 修改後通過「極簡測試腳本」的成功率。