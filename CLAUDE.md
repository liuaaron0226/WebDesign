# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A single-file Flask web app that solves the Petrick's (Patrick) Method for minimal SOP (Sum of Products) Boolean simplification, supporting both single- and multiple-output problems. The UI and comments are in Traditional Chinese. The entire application — routes, solver logic, and the inline HTML template — lives in `patrick_method_solver.py`.

## Commands

```bash
pip install -r requirements.txt   # Flask 3.1 and its dependencies
python patrick_method_solver.py   # runs on 0.0.0.0, port from $PORT (default 5000)
```

There are no tests, linters, or build steps in this repository. The app is deployed to Render, which supplies the `PORT` environment variable — keep the `0.0.0.0` host binding intact.

Note: `requirements.txt` is UTF-16 encoded (saved on Windows). `pip` handles it, but naive text tools may show garbled content; preserve or normalize the encoding deliberately if you edit it.

## Verification workflow (驗收流程)

`REQUIREMENTS.md` is the single source of truth for acceptance criteria. These rules are mandatory:

- Any task that modifies code MUST run the `/verify` acceptance loop (defined in `.claude/commands/verify.md`) before being declared complete — even if the user didn't ask for verification. The loop: start the app, test every item in `REQUIREMENTS.md` with real requests, fix failures, regression-retest, repeat until all pass.
- The final report MUST include the full per-item result table. Any ❌ means the task is NOT complete; if an item still fails after 3 fix rounds, stop and report the blocker honestly instead of claiming success.
- If a new task introduces new requirements, add them to `REQUIREMENTS.md` first, then implement.
- Testing gotchas: use `curl --form-string` (not `-F`) for inputs containing `;`, and match `&#39;` for apostrophes in HTML responses. The built-in default example's F0 is mathematically unsolvable — "找不到涵蓋所有 minterm 的組合" there is correct behavior, not a bug.

## Architecture

Everything is in `patrick_method_solver.py`:

- **Web layer**: one route (`/`, GET+POST) rendering `HTML_PAGE` via `render_template_string`. Input arrives either from two form textareas or an uploaded `.txt` file (line 1 = prime implicants, line 2 = minterms).
- **Input format**: multiple outputs are separated by `;`, terms/minterms within one output by `,`. Example: PIs `A'B, AB; A'C` with minterms `1,3; 2,6` describes two functions F0 and F1. `parse_input` zips the PI groups with the minterm groups positionally.
- **Solver pipeline** for each output: `build_prime_chart` (maps each minterm to the PIs covering it) → `find_min_sop` (brute-force search over PI combinations of increasing size, returning the first combination that covers all minterms — guaranteeing minimal cardinality).
- **Boolean-term evaluation**: `get_covered_minterms` enumerates all assignments over a fixed variable order `A, B, C, D` (the app supports at most four variables) and tests each against the PI expression via `match_pi`/`split_literals`. Complemented literals are written with a trailing apostrophe (e.g. `A'B`), and a PI expression may itself contain `+`-separated parts.

Constraints baked into the code: 4 variables max, minterm indices derived from the binary assignment of `A..D` (A is the most significant bit), and minterms that aren't plain digits are silently dropped during parsing.

## 使用者溝通側寫 (User communication profile)

本節來自對使用者實際對話的逐字稿分析(用詞風格、逐回合命中率稽核、規則提煉、批判檢查),供每個 session 開場即理解使用者。使用者自認不擅長下提示詞,期望 Claude 主動轉譯其口語需求,而非要求他寫得精確。

**語言**:全程以繁體中文回覆(程式碼、指令、檔名、commit 訊息除外)。

**解讀規則**:
- 「我在思考要如何X」「我先統整一下…」「可以用X去…」= 正式行動請求,直接受理執行,不是閒聊或徵詢可行性。
- 訊息常為逗號連寫的長句,結構是「背景→歸因→目的→請求」;真正的請求常埋在句子中段,句尾「目的是為了…」子句是不可妥協的驗收標準——方法可以換,目的不能丟。
- 同音別字照讀音還原(不段=不斷、所以有=所有、有訂=有定),不糾正、不因字面歧義反問。疑問句常無問號、祈使句常無「請」,皆為正常請求。
- 抱怨句中的「他」指過往 session 的 Claude;「上個對話」= 同視窗上一輪;「其他聊天視窗」= 跨 session 記錄(實際不可讀取)。
- 「潦草解決/潦草結束」= 在抱怨「宣稱完成但要求沒達成」,解方永遠是附證據的逐項驗收。

**回報格式**:先講結果再講細節;完成宣稱必須附逐項證據表(見 Verification workflow);過程要可追溯(分支、commit hash)——使用者會在數輪後回頭追問「上次執行了什麼」。

**譬喻政策**:git/GitHub/部署概念用生活譬喻解釋(已建立且有效:PR=簽核單、main=正式菜單、merge=簽核通過),需要使用者操作時給「你只要做一件事」的單一步驟。但布林邏輯領域術語(minterm、SOP、PI)不需譬喻——使用者熟悉此領域,過度譬喻反而是噪音。

**不留功課**:不要請使用者自行撰寫規格或驗收條目(實證:多次建議自行填寫 REQUIREMENTS.md 皆未執行)。改為從其敘述中主動萃取需求、代寫成可驗證條目、再向其確認。

**控制權**:不可逆動作(開 PR、merge、刪除)先告知選項、由使用者最終確認;回覆結尾提供可照抄的一句話指令(如「幫我盯 PR #2」),使用者會逐字採用。

**優先序**:要求確實達成 > 實測證據 > 省使用者時間 > 誠實透明 > 省用量。絕不因省用量或省輪次而壓縮品質或提早收尾——使用者明確表示寧可多耗用量。

**期望管理**:使用者預期 Claude 有跨視窗的連續記憶。新 session 應主動說明「對你的理解來自本檔案的側寫」,不假裝記得未記錄的事;如需更深入的長期理解,請使用者匯出過往對話上傳後再分析。
