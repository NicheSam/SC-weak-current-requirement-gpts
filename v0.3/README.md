# 模組一：弱電需求轉譯與 HTML 需求圖譜 GPTS

本模組把統包需求書及審查資料轉成以需求樹為主要入口的弱電需求成果。

正式交付只有：

- `demand_map.html`
- `to_xmind.md`
- `todo_handoff.md`

`m1_outputs.zip` 只是三檔封裝。本模組不是 CAD、正式報價、BIM 模型或 M2／M4 mapping 的正式資料源。

## 核心流程

```text
PDF／審查資料
→ 程式分批擷取原生文字、表格、OCR、頁碼與上下文
→ 所有可讀來源片段進入 AI 閱讀批次
→ AI 逐批抽取弱電相關、疑似相關及必要上下文
→ 依群組輪廓做一次文件級漏項複核
→ weak_current_source.md
→ stage1_receipt.json（來源階段完成證明）
→ AI 依舊版方式理解、合併、拆分與工程轉譯
→ requirements_master.md
→ demand_map.html、to_xmind.md、todo_handoff.md
```

第一階段只解決「從大量 PDF 中穩定找出弱電資訊」。第二階段才負責正式需求、系統分類、主題、人工確認與閱讀排版。

程式不得用關鍵字表、語意分數、預設系統路由或欄位規則代替 AI 判斷工程語意，也不得因一般影像文字仍低信心而阻斷全案。

## 使用者操作

使用者上傳 PDF 後直接執行第一階段。品質優先於執行時間，分批只保存進度與上下文，不得縮減頁面覆蓋或 OCR；大型 PDF 接近或超過一小時可以接受。第一階段完成後必須先提供 `weak_current_source.md` 與 `stage1_receipt.json`，不得在同一回合偷跑第二階段。使用者檢視後輸入一次「繼續」，GPTS 才核對第一階段成果並執行 AI 轉譯與正式交付；不需要第二次「繼續」，也不得要求重新上傳 PDF 或中間檔。

## 弱電範圍

弱電範圍以業務語意判斷，不依固定章號或封閉關鍵字：

- 電信、電話、行動通訊與訊號涵蓋。
- 資訊網路、光纖、銅纜、同軸、機櫃及弱電基礎設施。
- 電視、影音、顯示、廣播、對講與求救。
- 監視、門禁、停車、辨識、感測、告警與保全。
- BMS／BA、EMS、IoT、資料平台、資安及跨系統介面。
- 非弱電專業與弱電間的訊號、資料、監測、控制及連動。

4G／5G、洩波同軸、E-TAG、車牌辨識與讀卡只是回歸證據，不是產品邊界。

## 程式與 AI 分工

程式負責：

- PDF 文字、表格、OCR、頁碼及固定批次。
- 建立包含所有可讀來源片段的小批來源檔。
- 確認所有來源批次、頁碼與群組已讀，且來源檔名與 SHA 一致。
- 投影三份成果並檢查 ID、頁碼、連結與占位符。

AI 負責：

- 判斷弱電業務相關性。
- 保留必要上下文並建立 `weak_current_source.md`。
- 合併跨頁義務、拆分不同需求、保留否定與例外。
- 撰寫完整工程需求、系統摘要、主題設計重點及人工確認。
- 依舊版閱讀方式組織需求樹與詳細資訊。

## 合格標準

1. 所有來源閱讀批次都已由 AI 處理，頁碼與群組 marker 和 manifest 一致。
2. `stage1_receipt.json` 的來源包雜湊、PDF 頁數及批次覆蓋與實際檔案一致。
3. 弱電相關來源保留頁碼、短原文與足夠上下文。
4. 未知案型不因未命中既有詞表而消失。
5. 正式需求自然、完整、可獨立設計或查核。
6. 轉譯與閱讀品質至少達到舊版成果。
7. 需求樹保留完整需求文字，採固定清單與按需詳情。
8. 三份交付的需求文字、ID 與數量一致。

## 本地指令

```powershell
python m1_prepare_batches.py input.pdf m1_batches --batch-pages 5
python m1_prepare_batches.py --run-next m1_batches/batch_manifest.json
python m1_merge_candidate_batches.py m1_batches/batch_manifest.json source_index.json m1_candidates.json source_reading_pack.md --screening-dir m1_screening
# AI 逐批建立 screen_result_###.md
python m1_build_source_dossier.py --build-weak-current-source m1_screening/screen_manifest.json --weak-current-output weak_current_source.md --stage1-receipt stage1_receipt.json
# AI 依 weak_current_source.md 建立 requirements_master.md
python render_m1_outputs.py requirements_master.md weak_current_html_template.html m1_delivery --weak-current-source weak_current_source.md --stage1-receipt stage1_receipt.json
python -m unittest discover -s tests -v
```
