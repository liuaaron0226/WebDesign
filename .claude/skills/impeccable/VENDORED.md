# Vendored: Impeccable

本目錄是第三方套件的原封複製,**請勿手動編輯**。要升級請重跑下面的取得步驟。

| 項目 | 值 |
|---|---|
| 上游 | https://github.com/pbakaus/impeccable |
| 釘住 commit | `251135e1900662ed048dda391211f1895ab42d7e` |
| 套件版本 | 3.5.0(SKILL.md 內標 `version: 4.0.4`) |
| 授權 | Apache-2.0(見同目錄 `LICENSE`、`NOTICE.md`) |
| 取得日期 | 2026-08-12 |

本 repo 主體為 MIT(見根目錄 `LICENSE`);本目錄下的檔案依 Apache-2.0 授權,兩者並存不衝突。

## 取得方式(升級時重跑)

```bash
git clone https://github.com/pbakaus/impeccable.git /tmp/impeccable-src
cd /tmp/impeccable-src && git checkout <new-sha>
cp -r /tmp/impeccable-src/.claude/skills/impeccable <repo>/.claude/skills/
cp /tmp/impeccable-src/.claude/agents/*.md <repo>/.claude/agents/
cp /tmp/impeccable-src/{LICENSE,NOTICE.md} <repo>/.claude/skills/impeccable/
```

## 本專案做的取捨(與上游預設不同之處)

1. **未複製**上游 root 的 `CLAUDE.md` / `AGENTS.md` / `PRODUCT.md` / `DESIGN.md` —— 那是 Impeccable 自己專案的檔案,複製過來會蓋掉本 repo 的規範。本專案的 `PRODUCT.md` / `DESIGN.md` 是另外依自身識別撰寫的。
2. **完全未啟用上游的 hook**(`PostToolUse` 與 `Stop` 都沒接),因此本 repo 沒有 `.claude/settings.json`。
   這是實測後的決定,不是偷懶——理由見下面「為什麼不接 hook」。
3. **偵測器跑在抽取後的 HTML 上**,不是直接跑在原始碼上。原因見下節。
4. 檢查入口是 `python tools/design_check.py`,走 `npx impeccable@3.5.0`(套件自帶相依)。

## 為什麼不接 hook

上游 `.claude/settings.json` 會註冊 `PostToolUse`(Edit/Write/MultiEdit,5 秒)與 `Stop`(每輪 30 秒)
兩個 hook,都執行 `scripts/hook.mjs`。實測兩種輸入:

```
$ echo '{"hook_event_name":"PostToolUse",...,"file_path":".../inventory_app.py"}' | node scripts/hook.mjs
(無輸出,exit 0)

$ echo '{"hook_event_name":"PostToolUse",...,"file_path":".../ui_snapshot/index.html"}' | node scripts/hook.mjs
impeccable detect: DEGRADED - HTML parser modules unavailable (htmlparser2, css-select,
css-tree, domutils). Falling back to regex matching. ... findings are an undercount,
not a clean bill of health.
{"...":"Design hook scanned ui_snapshot/index.html. No deterministic design-quality issues found."}
```

兩個問題:

1. **對 `.py` 完全靜默。** hook 只看「剛被編輯的那個檔案」,而本 repo 的 UI 改動一律發生在
   `inventory_app.py`。它永遠不會有反應。
2. **對 `.html` 會產生假通過。** vendored 目錄沒有帶 npm 相依,偵測器退化成 regex 比對。
   它會自己警告「這是低估值」,但結論那行印的是 **No design-quality issues found**——
   而同一個檔案用完整的 `npx impeccable detect` 是掃得出 side-tab 等問題的。

一個永遠沉默、另一個會說謊。所以本專案改用要手動跑、但結果正確的
`python tools/design_check.py`。若日後要接 hook,前提是先把
`htmlparser2 / css-select / css-tree / domutils` 裝進專案(需要 `node_modules`,
與本專案「下載 ZIP 覆蓋」的散佈方式衝突)。

## 為什麼需要 `tools/extract_ui.py`

Impeccable 偵測器的可掃描副檔名(`scripts/detector/node/file-system.mjs` 的 `SCANNABLE_EXTENSIONS`)是:

```
.html .htm .css .scss .sass .less .jsx .tsx .js .ts .vue .svelte .astro .blade.php
```

**沒有 `.py`**。本專案的 UI 全部寫在 `inventory_app.py` 的 Python 字串裡(`LAYOUT`,含約 320 行 inline CSS),所以直接對 repo 執行偵測會掃到 0 個檔案、回報 0 個問題,看起來像「全部通過」,實際上是根本沒檢查。

`tools/extract_ui.py` 用 Flask test client 把實際算繪出來的頁面寫成獨立 `.html`,偵測器才有東西可讀。**任何時候看到偵測結果,請先確認它回報的掃描檔數不是 0。**
