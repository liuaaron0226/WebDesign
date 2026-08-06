---
description: 逐項對照 REQUIREMENTS.md 實測驗收,循環修正直到全部通過
---

對本專案執行完整的驗收循環。嚴格依下列步驟進行,不得省略任何項目:

1. **讀取清單**:讀取 `REQUIREMENTS.md`,列出所有驗收項目(包含「庫存管理系統」區與「使用者自訂要求」區)。忽略 checkbox 的已勾選狀態——每一項都要重新實測。

2. **啟動兩個 app**:確認依賴已安裝(必要時 `pip install --ignore-installed -r requirements.txt`),然後以背景執行啟動:
   - Patrick 化簡器:`PORT=5001 python patrick_method_solver.py`
   - 庫存管理系統(每輪都要先清掉測試 DB 與照片目錄取得乾淨狀態):
     `rm -rf /tmp/verify_inventory.db /tmp/inv_cookies.txt /tmp/verify_inventory_images && INVENTORY_DB=/tmp/verify_inventory.db INVENTORY_IMAGES=/tmp/verify_inventory_images PORT=5002 python inventory_app.py`

   等待 2 秒後確認兩個 port 皆可連線。

3. **逐項實測**:依每項的「驗證」欄位實際執行測試指令。注意:
   - `curl` 測含 `;` 的多輸出輸入時必須用 `--form-string`,不能用 `-F`。
   - 回應中的 `'` 會被 HTML 轉義為 `&#39;`,比對時要用轉義後的字串。
   - 庫存系統條目有**順序相依**(註冊→登入→建供應商→建商品→入出庫→報表),必須依清單順序執行;session 測試共用 cookie jar `/tmp/inv_cookies.txt`。
   - 無法用指令自動測試的項目,改以讀碼檢查並在結果表註明「讀碼驗證」。
   - 「已知行為」區列出的是正確行為,不得當成 bug 修改。

4. **修正循環**:對每個 ❌ 項目:修正程式 → 重測該項 → **回歸重測所有先前已通過的項目**(確認沒有修壞別的;庫存系統的回歸要先刪 `/tmp/verify_inventory.db` 從頭跑)。重複此循環直到全部 ✅。若同一項目連續 3 輪修正仍失敗,停止循環,在最終回報中明確說明卡住的原因與已嘗試的做法——**此時不得宣稱任務完成**。

5. **清理**:結束前務必關閉所有背景 app process(`kill` 各 PID,含 ALLOWED_IPS 測試用的第三個實例),並刪除測試過程產生的暫存檔(`/tmp/verify_inventory.db`、`/tmp/verify_inventory_images/`、`/tmp/inv_cookies.txt`、測試用 CSV、測試圖片與 input.txt 等)。

6. **最終回報**:輸出完整的逐項結果表(項目名稱|✅/❌|實測證據摘要),一項都不能省略。全部 ✅ 才能宣稱驗收通過;任何 ❌ 都要如實回報,不得淡化或跳過。
