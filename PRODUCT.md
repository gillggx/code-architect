# Code Architect Agent — 功能介紹

> 你的 AI 程式碼設計夥伴。把任何一個專案目錄丟進來，AI 就會讀懂它的架構、回答你的問題、並且幫你修改或建立新的程式碼。

---

## 三個主要使用情境

### 🔍 解析現有專案
把你現有的程式碼庫丟進來，AI 會：
- 讀取每一個源碼檔案，建立架構記憶
- 找出設計模式（Repository、Factory、Middleware 等）
- 讓你用自然語言問任何架構問題

**適合：** 剛接手別人的專案、做 code review 前的 onboarding、或想知道某個功能在哪裡

---

### ✨ 建立全新專案
從零開始，AI 陪你走完整個流程：
1. 你描述你的想法（用中文就可以）
2. AI 問你幾個關鍵問題（技術棧、功能、部署方式）
3. AI 產出一份完整的 **Spec 規格書（Markdown）**
4. 你確認規格後，AI 開始建立所有檔案

**適合：** 快速 prototype、個人 side project、或需要一個起始架構的新功能模組

---

### 🗂 專案管理
查看你分析過的所有專案：
- 看每個專案的分析時間、模組數量
- 重新觸發分析（增量，只讀新增/修改的檔案）
- 清除不需要的專案記憶

---

## 功能詳解

### 分析引擎

| 功能 | 說明 |
|------|------|
| **AST 掃描** | 不用 LLM，先用語法樹把結構摸清楚 |
| **LLM 解讀** | 逐檔理解語意，建立記憶模組 |
| **大檔分塊** | 超過 8000 字元的檔案自動切塊，滾動式累積理解，不截斷 |
| **增量分析** | 用 MD5 + mtime 偵測變動，只重新讀取有改過的檔案 |
| **鎖定檔跳過** | `package-lock.json`、`yarn.lock` 等自動略過 |
| **即時進度** | 每分析一個檔案，Activity Feed 和 File Tree 即時更新 |

### Chat（問答模式）

- **RAG 搜尋**：你的問題會先在架構記憶裡搜索相關片段（BM25 + 向量混合）
- **Git 上下文**：Chat agent 自動注入最近的 commit 和 uncommitted changes
- **分析中提示**：如果分析還在進行中，agent 會告訴你記憶尚未完整
- **持久化記憶**：選擇專案時，過去分析的記憶會自動載入

### Edit Agent（程式碼修改）

| 功能 | 說明 |
|------|------|
| **Plan A / Plan B** | AI 同時產出兩個執行方案，信心度低時讓你選擇 |
| **大任務自動分段** | 超過 12 個步驟的計畫自動拆成多個 Phase，每 Phase 傳遞摘要 |
| **互動審核** | 每個檔案改動前顯示 diff，讓你選擇 Apply / Skip / Stop |
| **Auto-approve** | 開啟後直接套用所有改動，不再逐一詢問（切換按鈕在輸入欄） |
| **Shell 執行** | 可執行測試、安裝依賴、git 等指令（有安全白名單） |
| **Escalation** | 工具失敗時自動切到 Plan B；Plan B 也失敗時升級給人工處理 |
| **無迭代上限** | Agent 一直執行到任務完成為止，不會中途停住 |
| **SOUL.md** | 在任何專案根目錄放 `SOUL.md` 可定義 agent 的個性和限制 |

---

## UI 操作說明

### 首頁
打開 `http://localhost:3001` 看到三個功能卡片，點選對應的情境開始。

### 解析專案流程
1. 點「🔍 解析專案」→ 選擇或輸入目錄路徑
2. 系統預先掃描顯示檔案數量
3. 點「Start Analysis」→ 右側 Activity Feed 即時顯示進度
4. 分析完成後自動在 Chat 顯示架構摘要

### 建新專案流程
1. 點「✨ 建新專案」→ 進入引導式 Chat
2. 描述你的想法，AI 會問幾個問題
3. AI 產出 Spec 規格書，你可以確認或要求修改
4. 確認後選擇輸出目錄，AI 開始建立專案

### Chat 問答
- 分析完成後在底部輸入欄直接提問
- 支援中英文
- 例如：「這個專案的驗證機制是怎麼運作的？」

### Edit 模式
1. 底部切換到「Edit」模式
2. 描述要做什麼改動（例如「幫 login API 加上 input validation」）
3. AI 生成計畫，你確認後開始執行
4. 每個檔案改動會顯示 diff，你可以選擇套用或跳過

**底部工具按鈕（Edit 模式）：**
- 👁 → ✅ **Auto-approve**：開啟後自動套用所有改動
- 🔒 → 🔓 **Shell unrestricted**：開啟後允許執行任意 shell 指令

### 返回首頁
點左上角「← 首頁」按鈕回到功能選擇頁面。

---

## 快速開始

### 前置需求
- Python 3.13+
- Node.js 18+
- OpenRouter API Key（或本地 Ollama）

### 啟動
```bash
git clone https://github.com/gillggx/code-architect.git
cd code-architect
cp .env.example .env   # 填入 OPENROUTER_API_KEY
./start.sh
```

開啟瀏覽器：`http://localhost:3001`

### 最小 `.env` 設定
```env
OPENROUTER_API_KEY=sk-or-...
DEFAULT_LLM_MODEL=anthropic/claude-haiku-4-5
```

---

## SOUL.md — 定義 Agent 個性

在任何專案根目錄放一個 `SOUL.md`，可以控制 Edit Agent 的行為：

```markdown
# Agent Soul

## Personality
你是一個謹慎、注重安全的架構師。

## Constraints
- 不要在沒有確認的情況下刪除檔案
- 所有新功能都必須有對應的 unit test
- 優先選擇向後相容的修改方式
```

---

## 支援的語言 / 技術棧

分析引擎支援：Python、TypeScript/JavaScript（React、Node）、Go、Rust、Java、C/C++、C#、Ruby、PHP、Swift、Kotlin、Scala，以及 YAML、TOML、JSON 設定檔和 Markdown 文件。

Edit Agent 可安裝依賴：npm、pip、pnpm、yarn、bun、cargo、go mod、uv、poetry。

---

## Ports

| 服務 | Port |
|------|------|
| Backend API (FastAPI) | **8001** |
| Frontend (React) | **3001** |
