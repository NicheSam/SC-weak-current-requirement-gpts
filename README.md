# 弱電需求書解析與 CAD 任務拆解 GPT

本專案是用於「統包需求書 / 審查意見」弱電內容解析的 GPTS Knowledge 與提示詞套件。目標是協助弱電設計、估算與繪圖人員快速整理需求，減少重複翻查文件、釐清責任界面與建立初步待辦。

目前版本為 `v0.4`。此版本把 PDF 解析移到隨版本提供的 Docling 來源轉換器；工具支援一份主需求書與選填的審查／補充 PDF，並合併成保留文件角色、原檔名與獨立頁碼的 `source_document_clean.md`。GPTS 再由此完成弱電範圍判斷、需求拆分、工程轉譯與固定版面輸出。`v0.3` 保留為 GPTS 內直接處理大型 PDF 的實驗版本，`v0.2` 保留為 Tree-first 基準版本。

## 解決的問題

- 統包需求書篇幅長，弱電需求分散在多個章節。
- 審查意見格式不固定，弱電相關問題與回覆需要再整理。
- 使用者需要快速知道「哪些系統有要求、哪些要確認、哪些影響後續設計與估算」。
- 原始 HTML 報告雖然完整，但資訊量仍可能過大，不利於會議討論與人工審閱。

## 主要輸出

目前版本預設要求 GPTS 產出三份檔案：

| 檔案 | 用途 |
|---|---|
| `demand_map.html` | 給人閱讀的 Tree-first 弱電需求圖譜 |
| `to_xmind.md` | 直接複製 HTML 唯一需求樹主節點的 XMind 編輯檔 |
| `todo_handoff.md` | 給其他 AI 或人工接續使用的弱電案件交接檔 |

## 目前版本狀態

| 版本 | 狀態 | 說明 |
|---|---|---|
| `v0.1` | 已封裝 | HTML-first、摘要總覽、系統樹狀圖、審查意見整合、Markdown 旁支輸出 |
| `v0.2` | 基準版本 | Tree-first、唯一需求樹、詳細資訊查詢、XMind 主節點輸出 |
| `v0.3` | 開發中 | 全文分批擷取、OCR、弱電來源包、舊版式 AI 轉譯、固定需求樹與輕量 Harness |
| `v0.4` | 目前版本 | Docling 完整來源 Markdown、AI 全文語意轉譯、readable-v2 固定版面、可調整需求樹與詳情欄寬 |

## Repository 結構

```text
.
├─ README.md
├─ .gitignore
├─ v0.1/
├─ v0.2/
├─ v0.3/
└─ v0.4/
   ├─ 00_使用說明.md
   ├─ 01_智慧建築2024_HTML對應總覽.md
   ├─ 02_智慧建築六大指標_弱電關聯摘要.md
   ├─ 03_弱電系統分類與轉譯規則.md
   ├─ 04_機電設備規格抽取規則.md
   ├─ 05_HTML輸出欄位規則.md
   ├─ 06_需人工確認規則.md
   ├─ 07_需求樹狀圖層級規則.md
   ├─ 08_M1.5資料包輸出規則.md
   ├─ 09_審查意見整合規則.md
   ├─ 10_MD旁支輸出規則.md
   ├─ 11_M1輸出驗收與回歸測試規則.md
   ├─ 12_M1雙階段續接資料規則.md
   ├─ gpt_instructions_weak_current_html.txt
   ├─ gpts_prompt_human_html.txt
   ├─ docling_tool/
   │  ├─ install_docling.cmd
   │  ├─ launch_docling_ui.cmd
   │  ├─ README.md
   │  └─ docling/
   ├─ m1_*.py
   ├─ render_m1_outputs.py
   ├─ requirements_master_template.md
   ├─ weak_current_html_template.html
   ├─ tests/
   └─ optional_reference/
```

## 完整使用流程

```text
主需求書 PDF ＋ 選填的審查／補充 PDF
                ↓
      本機 Docling 來源轉換器
                ↓
      source_document_clean.md
                ↓
              GPTS
                ↓
demand_map.html ＋ to_xmind.md ＋ todo_handoff.md
```

Docling 只負責把 PDF 轉成保留來源、頁碼、表格與上下文的 Markdown；弱電範圍判斷、需求拆分與工程語言轉譯仍由 GPTS 完成。

### 1. 環境需求

- Windows 10／11。
- Python 3.12，安裝時須包含 Python Launcher `py`。
- 第一次安裝套件及第一次下載 Docling／OCR 模型時需要網路。
- 大型或掃描型 PDF 需要較長處理時間，並應保留足夠記憶體與磁碟空間。
- 可使用本專案 GPTS 的 ChatGPT 帳號；自行建立 GPTS 時則需具備 GPT Builder 編輯權限。

> Docling 會安裝在 `v0.4/docling_tool/.venv`，不會取代或修改電腦既有的 Python 環境。

### 2. 下載與安裝 Docling

1. 從 GitHub 下載本專案 ZIP 並解壓縮，或使用 Git clone 取得專案。
2. 開啟 `v0.4/docling_tool/` 資料夾。
3. 雙擊 `install_docling.cmd`。
4. 等待視窗顯示 `Docling installation completed.`。第一次安裝需下載 Python 套件，時間取決於網路速度。

若安裝器顯示找不到 Python Launcher，請先安裝 Python 3.12，安裝時勾選 Python Launcher，完成後重新執行安裝器。

### 3. 開啟 Docling 介面

1. 雙擊 `launch_docling_ui.cmd`。
2. 瀏覽器會開啟 `http://127.0.0.1:8765/`。
3. 若瀏覽器沒有自動開啟，請自行將上述網址貼到瀏覽器。

這是使用者電腦上的本機介面，不會把工程文件上傳到本專案的 GitHub repository。

### 4. 轉換案件文件

1. 在「主需求書」選擇一份統包需求書或主要規範 PDF。
2. 如有審查意見、會議紀錄、補充說明或回覆文件，在附加文件欄多選加入；沒有則留空。
3. 按下「開始／續跑」。每份 PDF 會各自保留處理進度，意外關閉後可重新開啟介面續跑。
4. 所有文件完成後，下載合併的 `source_document_clean.md`。

來源角色會保留在合併檔中：

- `primary_requirements`：主需求書。
- `review_comments`：審查意見、會議紀錄、補充說明或回覆文件。
- 每份文件保留原始檔名及各自的 PDF 頁碼，避免不同文件的同頁碼互相混淆。

一般使用只需要下載 `source_document_clean.md`。`source_document.md`、`ocr_review_alternatives.md` 與 `manifest.json` 是 OCR 覆核及來源追溯資料，不需上傳 GPTS。

### 5. 上傳 GPTS 並取得成果

1. 開啟本專案的弱電需求書解析 GPTS。
2. 使用目前帳號可選用的模型；本流程不綁定特定模型名稱。
3. 上傳 Docling 產生的 `source_document_clean.md`，要求 GPTS 開始解析。
4. 等待 GPTS 完成需求判斷、拆分、工程轉譯及輸出。
5. 下載 `demand_map.html`、`to_xmind.md` 與 `todo_handoff.md`。

為避免 ChatGPT 頁面因大型 HTML 預覽而變慢，請下載 `demand_map.html` 後在本機瀏覽器開啟，不要要求 GPTS 在對話中展開 HTML 預覽。

### 6. 常見問題

| 狀況 | 處理方式 |
|---|---|
| `install_docling.cmd` 顯示找不到 `py` | 安裝 Python 3.12 並包含 Python Launcher，再重新執行安裝器。 |
| 第一次安裝或第一次轉換很久 | Docling 可能正在下載套件或模型；大型、掃描型 PDF 的 OCR 本來也會花較長時間。 |
| 雙擊啟動器後沒有看到介面 | 手動開啟 `http://127.0.0.1:8765/`；若仍無法開啟，再檢查是否已完成安裝。 |
| 處理途中關閉視窗 | 重新執行 `launch_docling_ui.cmd`，載入同一案件後按「開始／續跑」。 |
| 有另一份審查意見 PDF | 主需求書放第一欄，審查意見放附加文件欄；不要先把兩份 PDF 人工合併。 |
| GPTS 只收到 OCR 輔助檔 | 正常流程只上傳合併完成的 `source_document_clean.md`。 |

Docling 的檔案結構、測試指令與技術限制請見 [`v0.4/docling_tool/README.md`](v0.4/docling_tool/README.md)。

## GPTS 建置方式

以下內容只供需要自行建立或維護 GPTS 的管理者使用；一般使用者不需要設定 Knowledge。

1. 在 GPT Builder 的 Instructions 中貼入 `v0.4/gpts_prompt_human_html.txt`。
2. 將 `v0.4/` 內的正式規則、模板與執行腳本上傳到 Knowledge。
3. 若 GPT Builder 對中文檔名上傳不穩定，可先將檔名改為英文，但保留中文內容。
4. 使用者上傳合併後的 `source_document_clean.md`；附加文件已包含在同一來源包，不必再分別上傳 GPTS。
5. GPTS 依規則輸出 `demand_map.html`、`to_xmind.md`、`todo_handoff.md`。

## v0.4 設計重點

- 預設開啟 `需求樹核心`，不是摘要或 Dashboard。
- Docling 負責 PDF 文字、表格、OCR 與頁碼保存；GPTS 不再於單一回合內執行長時間 PDF OCR。
- GPTS 直接閱讀完整來源 Markdown，以全文語意判斷弱電業務範圍，不依固定章節或關鍵字白名單。
- HTML 需求樹、`to_xmind.md` 與詳細資訊查詢區共用同一份唯一需求樹。
- 需求樹與右側詳情可調整欄寬；畫面顯示 PDF 頁碼，不重複顯示 Docling 中間檔名。
- `to_xmind.md` 只複製需求樹主節點，不帶來源頁碼、狀態標籤、審查意見或短摘錄。
- 詳細資訊查詢區負責統需書頁碼、短摘錄、審查意見、設備規格與待辦釐清。

## 限制

- 主要交付仍是給人看的 HTML，不是正式資料庫。
- 不直接串接 CAD、QTO、報價單或 M2 / M4 mapping。
- 不產生正式 RFI、正式責任分工、正式報價數量或智慧建築得分判定。
- `to_xmind.md` 不承擔查核或交接功能；查核資訊放在 HTML 詳細資訊查詢與 `todo_handoff.md`。

## 授權與注意事項

目前未指定正式授權條款。若要公開給外部單位使用，建議後續補上 License，並確認範例文件、業主資料與專案內容未被放入公開 repo。
