---
description: 逐項對照 REQUIREMENTS.md 實測驗收,循環修正直到全部通過
---

對本專案執行完整的驗收循環。嚴格依下列步驟進行,不得省略任何項目:

1. **讀取清單**:讀取 `REQUIREMENTS.md`,列出所有驗收項目(包含「庫存管理系統」區與「使用者自訂要求」區)。忽略 checkbox 的已勾選狀態——每一項都要重新實測。

2. **先跑自動化測試**:`python test_inventory.py` 必須全綠(結束碼 0、輸出含 `OK`)。此測試覆蓋 FIFO、批次帳恆等式、加權平均成本、ABC 分級、權限控制、輸入邊界與 CSV 安全;有紅燈先修到綠再往下走。

3. **啟動兩個 app**:確認依賴已安裝(必要時 `pip install --ignore-installed -r requirements.txt`),然後以背景執行啟動:
   - Patrick 化簡器:`PORT=5001 python patrick_method_solver.py`
   - 庫存管理系統(每輪都要先清掉測試 DB 與照片目錄取得乾淨狀態):
     `rm -rf /tmp/verify_inventory.db* /tmp/inv_cookies.txt /tmp/verify_inventory_images /tmp/backups /tmp/secret_key.txt && INVENTORY_DB=/tmp/verify_inventory.db INVENTORY_IMAGES=/tmp/verify_inventory_images PORT=5002 python inventory_app.py`
   - 部分第四階段條目需要額外實例(ALLOWED_IPS 白名單用 PORT=5004),測畢務必 kill。
   - 第五階段(盤點/預留/規劃)條目接續同一測試序列;中文的 query 參數(如 `purpose=盤點調整`)
     必須用 `curl --get --data-urlencode`,直接塞進 URL 會查不到。

   等待 2 秒後確認兩個 port 皆可連線。

4. **逐項實測**:依每項的「驗證」欄位實際執行測試指令。注意:
   - `curl` 測含 `;` 的多輸出輸入時必須用 `--form-string`,不能用 `-F`。
   - 回應中的 `'` 會被 HTML 轉義為 `&#39;`,比對時要用轉義後的字串。
   - 庫存系統條目有**順序相依**(註冊→登入→建供應商→建商品→入出庫→報表),必須依清單順序執行;session 測試共用 cookie jar `/tmp/inv_cookies.txt`。
   - 無法用指令自動測試的項目,改以讀碼檢查並在結果表註明「讀碼驗證」。
   - 「已知行為」區列出的是正確行為,不得當成 bug 修改。

5. **修正循環**:對每個 ❌ 項目:修正程式 → 重測該項 → **回歸重測所有先前已通過的項目**(確認沒有修壞別的;庫存系統的回歸要先刪 `/tmp/verify_inventory.db` 從頭跑)。重複此循環直到全部 ✅。若同一項目連續 3 輪修正仍失敗,停止循環,在最終回報中明確說明卡住的原因與已嘗試的做法——**此時不得宣稱任務完成**。

6. **清理**:結束前務必關閉所有背景 app process(`kill` 各 PID,含 ALLOWED_IPS 測試用的第三個實例),並刪除測試過程產生的暫存檔(`/tmp/verify_inventory.db*`(含 -wal/-shm)、`/tmp/verify_inventory_images/`、`/tmp/backups/`、`/tmp/secret_key.txt`、`/tmp/inv_cookies.txt`、測試用 CSV、測試圖片與 input.txt 等)。

7. **最終回報**:輸出完整的逐項結果表(項目名稱|✅/❌|實測證據摘要),一項都不能省略。全部 ✅ 才能宣稱驗收通過;任何 ❌ 都要如實回報,不得淡化或跳過。
