# Docling 多文件來源轉換器

此工具在使用者電腦本機把大型 PDF 轉成 GPTS 易讀的 Markdown。它不做弱電需求判斷或工程轉譯；這些工作仍由 GPTS 完成。

## 環境需求

- Windows 10／11
- 首次安裝及首次載入模型時需要網路
- 64 位元 Windows 10／11
- 至少 3 GB 可用磁碟空間；大型或掃描型 PDF 建議保留更多記憶體與空間

不需要事先安裝 Python。安裝器會在本資料夾內建立 Docling 專用的 `uv`、Python 3.12 與 `.venv`，不會修改系統 PATH 或取代電腦既有的 Python。一般安裝不需要管理員權限；只有電腦缺少 Microsoft Visual C++ Runtime 時，Windows 會要求一次系統管理員核准。

## 安裝與開啟

1. 雙擊 `install_docling.cmd`。不要直接開啟 `install_docling.ps1`；該檔是由 CMD 啟動器在內部呼叫。
2. 第一次執行會檢查系統架構、資料夾權限、磁碟空間，再下載專用 Python、建立 `.venv`，並安裝 Docling／RapidOCR。
3. 安裝器會實際載入 Torch、OCR 與 Docling。若缺少 Microsoft Visual C++ Runtime，請允許 Windows 顯示的安裝核准視窗。
4. 安裝完成後執行 `launch_docling_ui.cmd`。
5. 瀏覽器會開啟本機介面 `http://127.0.0.1:8765/`。

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

## 錯誤代碼

介面會在開始逐頁處理前檢查執行環境。環境錯誤會立即停止，不會對每一頁重複同一錯誤。

| 代碼 | 原因 | 建議處理 |
|---|---|---|
| `E_VC_RUNTIME`／`E_TORCH_RUNTIME` | Visual C++ Runtime 缺少、過舊或 Torch 原生元件無法載入 | 重新執行 `install_docling.cmd` 並允許安裝微軟 Runtime；公司電腦若阻擋安裝，交由資訊人員處理 |
| `E_DEPENDENCY_MISSING`／`E_DOCLING_RUNTIME` | 私有環境缺件或被移動 | 刪除整個工具資料夾後重新解壓縮，再執行安裝器 |
| `E_NETWORK` | 下載被代理、防火牆、憑證檢查或斷線阻擋 | 確認能連線至 Microsoft、astral.sh、PyPI 與模型來源 |
| `E_PERMISSION` | 安裝或案件資料夾不可寫、PDF 被鎖定 | 移到使用者可寫入的本機資料夾並關閉占用 PDF 的程式 |
| `E_DISK_SPACE` | 磁碟空間不足 | 保留至少 4 GB 可用空間 |
| `E_PATH_TOO_LONG` | 解壓縮或案件路徑過長 | 將工具移到短路徑，例如 `C:\Docling` |
| `E_MEMORY` | 記憶體不足 | 關閉大型程式；必要時拆分大型掃描 PDF |
| `E_PDF_INVALID` | PDF 損壞、無法開啟或有密碼 | 另存無密碼的新 PDF 後重試 |
| `E_RUNTIME` | 尚未分類的錯誤 | 保留錯誤代碼與處理紀錄並回報維護者 |

## 限制

- 同時間只處理一組案件文件。
- OCR 與版面解析時間取決於頁數、掃描品質及電腦效能。
- 本工具不判定弱電業務邊界，也不把審查意見直接轉成正式需求。
