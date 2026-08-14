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
   ├─ m1_*.py
   ├─ render_m1_outputs.py
   ├─ requirements_master_template.md
   ├─ weak_current_html_template.html
   ├─ tests/
   └─ optional_reference/
```

## GPTS 使用方式

1. 使用 Docling 來源轉換器，將原始 PDF 轉成完整頁碼化的 `source_document_clean.md`。
   - 主需求書必選一份。
   - 審查意見、會議紀錄或回覆 PDF 可選填多份。
   - 操作方式見 `v0.4/docling_tool/README.md`。
2. 在 GPT Builder 的 Instructions 中貼入 `v0.4/gpts_prompt_human_html.txt`。
3. 將 `v0.4/` 內的正式規則、模板與執行腳本上傳到 Knowledge。
3. 若 GPT Builder 對中文檔名上傳不穩定，可先將檔名改為英文，但保留中文內容。
4. 使用者上傳合併後的 `source_document_clean.md`；審查文件已包含在同一來源包，不必再分別上傳 GPTS。
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
