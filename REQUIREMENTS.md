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

## 庫存管理系統(inventory_app.py)驗收

> 測試前置:先清掉測試資料庫再啟動,session 測試需 cookie jar。**本節條目有順序相依(註冊→登入→建供應商→建商品→入出庫→報表),必須依序執行**;每輪驗收都要先 `rm -f /tmp/verify_inventory.db` 取得乾淨 DB,否則「重複帳號」「首位管理員」等項會誤判。
>
> ```bash
> rm -f /tmp/verify_inventory.db /tmp/inv_cookies.txt
> INVENTORY_DB=/tmp/verify_inventory.db PORT=5002 python inventory_app.py &
> ```

- [ ] **未登入一律導向登入頁**:未帶 cookie GET `/` 回 302,跟隨後可見登入頁。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" http://localhost:5002/` 為 `302`;`curl -s -L http://localhost:5002/ | grep -c 登入` ≥ 1。
- [ ] **可註冊帳號,第一位自動為管理員;重複帳號被拒**。
  - 驗證:`curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/register --form-string "username=admin1" --form-string "password=pass1234"` 為 `302`;重送同帳號後輸出含「帳號已存在」;`python3 -c "import sqlite3; print(sqlite3.connect('/tmp/verify_inventory.db').execute('select is_admin from users where username=?',('admin1',)).fetchone())"` 為 `(1,)`。
- [ ] **登入成功建立 session、失敗顯示訊息**。
  - 驗證:`curl -s -c /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/login --form-string "username=admin1" --form-string "password=pass1234"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep 庫存總覽`;錯誤密碼 POST 後輸出含「帳號或密碼錯誤」。
- [ ] **供應商新增後列表可見**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/suppliers/new --form-string "name=大同貿易" --form-string "contact=王先生" --form-string "phone=0912345678"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/suppliers | grep 大同貿易`。
- [ ] **商品新增成功且 SKU 唯一**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/new --form-string "name=可樂" --form-string "sku=SKU001" --form-string "category=飲料" --form-string "unit=瓶" --form-string "unit_price=25" --form-string "low_stock_threshold=10" --form-string "supplier_id=1"` 為 `302`;首頁 grep `SKU001`;重送同 SKU 後輸出含「SKU 已存在」。
- [ ] **入庫增加庫存並記錄**:入庫 50 後庫存為 50。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/stock/in --form-string "product_id=1" --form-string "quantity=50" --form-string "note=首批進貨"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep 'id="qty-1">50<'`。
- [ ] **出庫減少庫存**:出庫 20 後庫存為 30。
  - 驗證:POST `/stock/out`(product_id=1, quantity=20)回 302;首頁 grep `id="qty-1">30<`。
- [ ] **出庫不得使庫存為負**:出庫 999 被拒、庫存不變。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -X POST http://localhost:5002/stock/out --form-string "product_id=1" --form-string "quantity=999" | grep 庫存不足`;首頁仍 grep 到 `id="qty-1">30<`。
- [ ] **搜尋商品**:`/?q=可樂` 有結果、`/?q=zzz` 顯示查無商品。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt --get --data-urlencode "q=可樂" http://localhost:5002/ | grep SKU001`(中文 query 必須用 `--data-urlencode` 正確編碼,直接塞進 URL 不符合 HTTP 規範會查不到);`curl -s -b /tmp/inv_cookies.txt "http://localhost:5002/?q=zzz" | grep 查無商品`。
- [ ] **低庫存警示**:再出庫 25(庫存 5 ≤ 門檻 10)後,首頁該列標示低庫存、`/alerts` 列出該商品。
  - 驗證:POST `/stock/out`(quantity=25)後,`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/ | grep low-stock`;`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/alerts | grep 可樂`。
- [ ] **異動歷史含操作人員並可篩選**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/history` 輸出同時含 `<td>入庫</td>`、`<td>出庫</td>`、`admin1`;`curl -s -b /tmp/inv_cookies.txt "http://localhost:5002/history?type=in" | grep -c '<td>出庫</td>'` 為 `0`(比對必須用 `<td>` 包住,否則會誤抓到導覽列的「出庫」連結)。
- [ ] **報表顯示進出統計與庫存價值**:目前狀態應為入庫總量 50、出庫總量 45、庫存 5、單價 25 → 庫存價值 125。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt http://localhost:5002/report` 輸出含 `50`、`45`、`125`(分別對應入庫、出庫、總價值,以報表列的 id 或欄位精準比對)。
- [ ] **CSV 匯出(UTF-8 BOM,Excel 中文不亂碼)**:兩個匯出端點皆為 text/csv、檔案開頭為 BOM、含中文內容。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /tmp/inv.csv -w "%{content_type}" http://localhost:5002/export/inventory.csv` 含 `text/csv`;`python3 -c "print(open('/tmp/inv.csv','rb').read(3)==b'\xef\xbb\xbf')"` 為 `True`;`grep 可樂 /tmp/inv.csv`;`/export/transactions.csv` 同法驗 BOM 且 grep `首批進貨`。
- [ ] **登出後失去存取權**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -c /tmp/inv_cookies.txt -o /dev/null http://localhost:5002/logout` 後,`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" http://localhost:5002/history` 為 `302`。
- [ ] **Render 綁定與依賴管理**:`app.run` 保持 `host="0.0.0.0"`、port 讀 `$PORT`(預設 5000);`requirements.txt` 維持 UTF-16 編碼且 pip 可解析,內容為 Flask + Pillow(以圖搜圖需要),無其他新增依賴。
  - 驗證:`grep -n 'host="0.0.0.0"' inventory_app.py` 與 `grep -n 'PORT' inventory_app.py` 皆有;`python3 -c "print(open('requirements.txt','rb').read(2))"` 為 `b'\xff\xfe'`;`python3 -c "print('Pillow' in open('requirements.txt', encoding='utf-16').read())"` 為 `True`;`pip install -r requirements.txt --dry-run` 成功。
- [ ] **inventory.db 不入版控**。
  - 驗證:`grep -n 'inventory.db' .gitignore` 有結果;`git status --porcelain | grep inventory.db` 為空。
- [ ] **原 Patrick app 不受影響**:上方「功能驗收」「部署約束」全部條目(PORT=5001)回歸通過。
  - 驗證:執行本清單上半部所有項目。

## 庫存系統第二階段:料號整合、照片、以圖搜圖、快速登記、內網限制

> 接續上節測試序列執行(同一個測試 DB;上節結尾已登出,本節開頭先重新登入)。照片目錄用 `INVENTORY_IMAGES=/tmp/verify_inventory_images` 啟動,每輪驗收先 `rm -rf` 該目錄。測試圖以 PIL 產生(純紅色 vs 黑白漸層,兩張截然不同)。

- [ ] **商品詳細頁**:GET `/products/1` 包含品名、庫存、「照片」區、「跨公司料號對照」區、「近期異動」區。
  - 驗證:重新登入後 `curl -s -b /tmp/inv_cookies.txt http://localhost:5002/products/1` 輸出含「可樂」「照片」「跨公司料號對照」「近期異動」。
- [ ] **跨公司料號別名:新增、用別名搜尋找到本尊、重複組合被拒**。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/1/aliases --form-string "company=台達電" --form-string "alias_sku=DELTA-123"` 為 `302`;`curl -s -b /tmp/inv_cookies.txt --get --data-urlencode "q=DELTA-123" http://localhost:5002/ | grep SKU001`;重送同組合輸出含「此公司+料號組合已存在」。
- [ ] **CSV 商品匯入(UTF-8)**:匯入 2 筆新商品(含初始庫存)成功,重複 SKU 列被跳過並回報行號原因;初始庫存產生 `in` 異動(note=CSV匯入)。
  - 驗證:製作 UTF-8 CSV(標題列 `SKU,名稱,分類,單位,單價,低庫存門檻,供應商,初始庫存`,含 SKU002 滑鼠/庫存 30、SKU003 鍵盤/庫存 20、SKU001 重複列),`curl -s -b /tmp/inv_cookies.txt -X POST http://localhost:5002/import -F "mode=products" -F "csv_file=@/tmp/test_products.csv"` 輸出含「成功匯入 2 筆」與「SKU 已存在」;首頁 grep `id="qty-2">30<`;`/history` 含「CSV匯入」。
- [ ] **CSV 商品匯入(cp950/Big5,台灣 Excel 編碼)**:cp950 編碼的 CSV 也能正確匯入中文。
  - 驗證:以 Python 產生 cp950 編碼 CSV(SKU004 螢幕),匯入後首頁 grep `SKU004` 與 `螢幕`。
- [ ] **CSV 別名匯入**:匯入後用別名料號搜尋找得到本尊商品。
  - 驗證:製作別名 CSV(標題列 `我方SKU,公司,別名料號,備註`,一列 `SKU002,群光,CHICONY-M100,`),匯入輸出含「成功匯入 1 筆」;`/?q=CHICONY-M100` grep `SKU002`。
- [ ] **照片上傳與顯示**:上傳 PNG 到商品後詳細頁出現 `<img`,檔案落在照片目錄;非圖片副檔名被拒。
  - 驗證:PIL 產生 `/tmp/red.png`(純紅)上傳 `curl -s -b /tmp/inv_cookies.txt -o /dev/null -w "%{http_code}" -X POST http://localhost:5002/products/1/images -F "photo=@/tmp/red.png"` 為 `302`;`/products/1` 含 `<img`;`ls /tmp/verify_inventory_images/ | grep -c png` ≥ 1;上傳 `.txt` 檔輸出含「不支援的檔案格式」。
- [ ] **以圖搜圖:最相似者排第一**:兩張截然不同的照片分掛兩商品後,用與其中一張相近的圖搜尋,第一名必須是掛該照片的商品。
  - 驗證:PIL 產生 `/tmp/gradient.png`(黑白漸層)上傳到商品 2;再以 `/tmp/red_query.png`(接近純紅、少量雜訊)POST `/search/image`,回應中 SKU001 出現位置早於 SKU002,且含「相似度」。
- [ ] **連續登記便利**:入庫成功後 302 導回入庫頁並顯示成功訊息(含品名與最新庫存),出庫同理。
  - 驗證:`curl -s -b /tmp/inv_cookies.txt -i -X POST http://localhost:5002/stock/in --form-string "product_id=1" --form-string "quantity=10" --form-string "note=連續登記測試" | grep -i "^location:"` 含 `/stock/in`;跟隨 redirect 後頁面含「入庫成功」與「目前庫存」。
- [ ] **ALLOWED_IPS 內網白名單**:未設定時行為完全不變(本清單其他條目即為證明);設定後非名單來源一律 403,名單內來源正常。
  - 驗證:另啟動一個實例 `ALLOWED_IPS=203.0.113.5 INVENTORY_DB=/tmp/verify_inventory.db PORT=5003 python inventory_app.py`;`curl -s -o /dev/null -w "%{http_code}" http://localhost:5003/` 為 `403` 且回應含「僅限公司內部網路」;`curl -s -o /dev/null -w "%{http_code}" -H "X-Forwarded-For: 203.0.113.5" http://localhost:5003/` 為 `302`(正常導向登入)。測畢 kill 該實例。
- [ ] **內網部署啟動腳本存在且正確**:`start_inventory.bat`(Windows)與 `start_inventory.sh`(Mac/Linux)皆存在,內容含依賴安裝與 `python inventory_app.py` 啟動(讀碼驗證)。
  - 驗證:`grep -l "inventory_app.py" start_inventory.bat start_inventory.sh` 列出兩檔;`bash -n start_inventory.sh` 無語法錯誤。

## 使用者自訂要求(請在此新增你在意的驗收項目)

<!-- 範例格式:
- [ ] **要求標題**:一句話描述預期行為。
  - 驗證:具體的測試指令或檢查步驟。
-->
