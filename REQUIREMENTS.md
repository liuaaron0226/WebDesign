# REQUIREMENTS.md — 驗收清單

本檔案是專案的**驗收依據**。任何程式修改在宣稱完成前,必須逐項對照本清單實際測試(執行 `/verify`)。每一項都要寫成「可實際驗證」的敘述,並附上驗證方式。

- 勾選狀態僅供人工追蹤;`/verify` 每次都會重新實測所有項目,不信任已勾選的狀態。
- 新任務若帶來新要求,**先把要求補進本清單**,再開始實作。

> 測試注意:用 `curl` 測多輸出時必須使用 `--form-string`(不能用 `-F`),否則值裡的 `;` 會被 curl 當成選項分隔符截斷。

## 功能驗收

- [ ] **首頁可載入**:GET `/` 回傳 HTTP 200,且頁面包含 `pi_input` 與 `minterms` 兩個 textarea 及檔案上傳欄位。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/` 應為 `200`;`curl -s http://localhost:5001/ | grep -c '<textarea'` 應為 `2`(注意要含 `<`,否則會多算到 CSS 裡的 `textarea` 選擇器)。
- [ ] **單輸出求解正確**:PI `A'C, AB`、minterms `2,3,12` 應得 `F0 → A'C + AB`。
  - 驗證:`curl -s -X POST http://localhost:5001/ --form-string "pi_input=A'C, AB" --form-string "minterms=2,3,12"`,輸出含 `A&#39;C + AB`。
- [ ] **多輸出(`;` 分隔)求解正確**:PI `A'B'C', A'B; A'C`、minterms `0,1,4; 2,6` 應得 `F0 → A'B'C' + A'B` 與 `F1 → A'C` 兩行結果。
  - 驗證:同上以 `--form-string` POST,輸出須同時含 `F0` 與 `F1` 行。
- [ ] **無解時顯示訊息而非報錯**:PI `AB`、minterm `0` 應顯示「找不到涵蓋所有 minterm 的組合」,HTTP 仍為 200。
  - 驗證:POST 後 grep 該訊息;不得出現 traceback 或 500。
- [ ] **`.txt` 上傳可覆蓋表單輸入**:上傳第 1 行為 PI、第 2 行為 minterms 的檔案,結果須依檔案內容計算(即使表單填了其他值)。
  - 驗證:`printf "A'C, AB\n2,3,12\n" > input.txt` 後以 `-F "input_file=@input.txt"` 上傳,輸出含 `A&#39;C + AB`。
- [ ] **求解結果為最小組合數**:`find_min_sop` 由小到大枚舉組合,回傳的 PI 個數必須是能涵蓋所有 minterm 的最少個數。
  - 驗證:讀碼確認枚舉順序未被更動;或設計一組有冗餘 PI 的輸入確認冗餘項未入選。

## 部署約束

- [ ] **Render 綁定不被破壞**:`app.run` 保持 `host="0.0.0.0"`,port 讀自環境變數 `PORT`(預設 5000)。
  - 驗證:`grep -n 'host="0.0.0.0"' patrick_method_solver.py` 與 `grep -n 'PORT' patrick_method_solver.py` 皆有結果。
- [ ] **`requirements.txt` 編碼不被意外破壞**:此檔為 UTF-16(Windows 存檔),`pip install -r requirements.txt` 必須能成功解析。
  - 驗證:`python -c "print(open('requirements.txt','rb').read(2))"` 應為 BOM `b'\xff\xfe'`;或直接跑 `pip install -r requirements.txt --dry-run`。

## 已知行為(非 bug,勿「修好」)

- 內建預設範例(PI `A'B, AB`、minterms `1,3`)的 F0 **數學上無解**(`A'B` 涵蓋 4–7、`AB` 涵蓋 12–15),顯示「找不到涵蓋所有 minterm 的組合」是正確結果。
- 變數固定為 `A,B,C,D` 四個,A 為最高位;非數字的 minterm 會被靜默略過。

## 使用者自訂要求(請在此新增你在意的驗收項目)

<!-- 範例格式:
- [ ] **要求標題**:一句話描述預期行為。
  - 驗證:具體的測試指令或檢查步驟。
-->
