# Domain Docs

engineering 系列 skill 在探索本 repo 時,應該怎麼讀領域文件。

## 探索前先讀

- **`CONTEXT.md`**(repo 根目錄)——本專案的統一語彙。
- **`docs/adr/`**——與你要動的區域相關的架構決策紀錄(目前尚無,第一則由 `/domain-modeling` 在真的做出決策時建立)。
- **`CLAUDE.md`**——本 repo 的架構與作法說明。`CONTEXT.md` 只定義「是什麼」,`CLAUDE.md` 講「怎麼做、為什麼」;兩者互補,不重複。

檔案不存在時**安靜略過**,不要特別提、也不要一開始就建議建立。`/domain-modeling`(可由 `/grill-with-docs` 與 `/improve-codebase-architecture` 進入)會在術語或決策真正被釐清時才產生它們。

## 檔案結構

本 repo 是**單一 context**:

```
/
├── CONTEXT.md
├── docs/adr/
├── inventory_app.py
└── patrick_method_solver.py
```

兩個 app 互不相依,但共用同一份 `CONTEXT.md`,詞彙分兩節列出(庫存管理系統 / Patrick 化簡器)。規模不足以拆成 multi-context,沒有 `CONTEXT-MAP.md`。

## 使用語彙表的詞

輸出中提到領域概念時(issue 標題、重構提案、假設、測試名稱),使用 `CONTEXT.md` 定義的詞,不要漂移到它明確標示 `_避免_` 的同義詞。

需要的概念還不在語彙表裡,那是個訊號——要嘛你正在發明專案不用的說法(請重新考慮),要嘛是真的缺口(記下來交給 `/domain-modeling`)。

## 與 ADR 衝突要講出來

若你的產出牴觸既有 ADR,明講出來,不要默默覆蓋:

> _與 ADR-0007(事件溯源訂單)牴觸——但值得重啟討論,因為……_
