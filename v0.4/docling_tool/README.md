# Docling 多文件來源轉換器

此工具在使用者電腦本機把大型 PDF 轉成 GPTS 易讀的 Markdown。它不做弱電需求判斷或工程轉譯；這些工作仍由 GPTS 完成。

## 環境需求

- Windows 10／11
- 首次安裝及首次載入模型時需要網路
- 大型或掃描型 PDF 建議保留充足記憶體與磁碟空間

不需要事先安裝 Python，也不需要管理員權限。安裝器會在本資料夾內建立 Docling 專用的 `uv`、Python 3.12 與 `.venv`，不會修改系統 PATH 或取代電腦既有的 Python。

## 安裝與開啟

1. 執行 `install_docling.cmd`。第一次執行會自動下載專用 Python、建立 `.venv`，並安裝 Docling／RapidOCR。
2. 安裝完成後執行 `launch_docling_ui.cmd`。
3. 瀏覽器會開啟本機介面 `http://127.0.0.1:8765/`。

首次安裝下載量較大，所需時間取決於網路速度。若中途中斷，可重新執行同一安裝器；已完成的下載會盡量從本機快取續用。

## 使用流程

1. 在「主需求書」選擇一份統包需求書或主要規範 PDF。
2. 若有審查意見、會議紀錄或回覆文件，可在第二欄多選加入。
3. 按「開始／續跑」。每份 PDF 會保有自己的 checkpoint。
4. 全部文件驗證完成後，下載合併的 `source_document_clean.md`。
5. 正常使用只需把這一個 MD 上傳 GPTS。

合併檔會保留：

- `primary_requirements`：主需求書
- `review_comments`：審查意見、會議紀錄或回覆
- 原始檔名
- 每份文件各自的 PDF 頁碼

因此主需求書第 5 頁與審查意見第 5 頁不會被視為同一來源。其他 `source_document.md`、`ocr_review_alternatives.md` 與 `manifest.json` 僅供 OCR 與來源追溯。

## 測試

```powershell
.venv\Scripts\python.exe -m unittest discover -s docling\tests -p "test_*.py" -v
```

## 限制

- 同時間只處理一組案件文件。
- OCR 與版面解析時間取決於頁數、掃描品質及電腦效能。
- 本工具不判定弱電業務邊界，也不把審查意見直接轉成正式需求。
